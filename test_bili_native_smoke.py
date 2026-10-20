"""
Smoke test for the Bilibili native segmented downloader (audio_utils).

Replays the reported failure mode locally, like the reference app's
download_url_reconnect_* tests: a mock CDN that closes connections
mid-range (Akamai-trim behaviour), a healthy mirror candidate, and a
checkpoint reuse scenario. Everything runs against stdlib
http.server on 127.0.0.1 - no network needed except for audio_utils'
module import.

    python test_bili_native_smoke.py

The fixture pattern matches the reference suite's byte recipe:
content[i] = (i % 251), so any mismatch in resume stitching shows up
immediately in a byte-for-byte comparison.
"""

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import audio_utils


TOTAL = 196608          # 192 KiB -> 3 x 64 KiB segments with the overrides
SEG_SIZE = 65536        # 64 KiB segments (segment boundaries: 0, 64K, 128K)
KILL_FIRST_BYTES = 8192  # first chunk served before a "CDN kill" closes in
DIE_BYTES = 1024         # /die: always near-zero progress before dying
TRIM_BYTES = 131072      # /trim: Akamai-style host that shortens ranges
BOUNDARY_LIST = [0, SEG_SIZE, 2 * SEG_SIZE]


def content_byte(i: int) -> int:
    return i % 251


def content_slice(start: int, end: int) -> bytes:
    """Reference fixture bytes [start, end) generated lazily."""
    return bytes(content_byte(i) for i in range(start, end))


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # connection: close on every response

    def log_message(self, *args):
        pass

    def do_GET(self):
        cfg = self.server.test_cfg
        spec = self.headers.get("Range") or ""
        try:
            spec = spec.split("=", 1)[1]
            start_s, end_s = spec.split("-", 1)
            start = int(start_s)
            end = int(end_s) if end_s else cfg["total"] - 1
        except (ValueError, IndexError):
            self.send_response(400)
            self.end_headers()
            return
        data = content_slice(start, min(end + 1, cfg["total"]))
        with cfg["lock"]:
            cfg["requests"].append((self.path, start, end))

        mode = cfg["mode"]
        served = None
        if mode == "ok":
            served = data
        elif mode == "die":
            served = data[:DIE_BYTES]  # always near-zero, never completes
        elif mode == "trim":
            # Serves ONLY TRIM_BYTES no matter how much was asked for -
            # the Akamai-trim failure mode the probe must catch.
            served = data[:TRIM_BYTES]
        elif mode == "kill":
            # Kill once per fresh segment boundary request; every other
            # request on this host (resume offsets, tail verifies, retries)
            # is served completely.
            if start in cfg["kill_starts"] and start not in cfg["killed"]:
                with cfg["lock"]:
                    cfg["killed"].add(start)
                served = data[:KILL_FIRST_BYTES]
            else:
                served = data

        total = cfg["total"]
        end_actual = start + len(served) - 1
        self.send_response(206)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Range", f"bytes {start}-{end_actual}/{total}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self.wfile.write(served)
        if len(served) < (end - start + 1):  # mid-flight close -> IncompleteRead
            self.close_connection = True


class _MockCdn:
    def __init__(self, mode: str, kill_starts=None):
        self.requests = []
        self.killed = set()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.test_cfg = {
            "mode": mode,
            "total": TOTAL,
            "requests": self.requests,
            "killed": self.killed,
            "kill_starts": set(kill_starts or []),
            "lock": threading.Lock(),
        }
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/audio.m4s"

    def stops(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class TestBiliSegmentedDownload(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ok = _MockCdn("ok")
        cls.kill = _MockCdn("kill", kill_starts=BOUNDARY_LIST)
        cls.die = _MockCdn("die")
        cls.trim = _MockCdn("trim")

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.ok, cls.kill, cls.die, cls.trim):
            srv.stops()

    def _download(self, tmp, candidates, url_path="jrpdlite/test", **kwargs):
        out = Path(tmp) / "audio.m4s"
        merged = dict(segment_size=SEG_SIZE, tail_verify=4096,
                      slow_limit=3, min_progress=1024)
        merged.update(kwargs)
        ok = audio_utils._bili_segmented_download(
            candidates, out, TOTAL, url_path, **merged)
        return ok, out

    def test_segmented_download_survives_mid_range_close(self):
        """The reported failure: edge closes mid-range; recovery must
        tail-verify the on-disk progress and resume it, never restart the
        file, and produce byte-exact output."""
        with tempfile.TemporaryDirectory() as tmp:
            ok, out = self._download(tmp, [self.kill.url, self.ok.url])
            self.assertTrue(ok)
            expected = content_slice(0, TOTAL)
            self.assertEqual(out.read_bytes(), expected, "resume stitching corrupted bytes")
            sidecar = audio_utils._bili_progress_sidecar_path(out)
            self.assertFalse(sidecar.exists(), "checkpoint must be removed on success")
            # Every segment boundary got exactly one mid-flight close.
            self.assertEqual(
                self.kill.killed, set(BOUNDARY_LIST),
                "each segment start should be killed exactly once per fresh run")

    def test_near_zero_progress_rotates_immediately(self):
        """/die never serves a full range: near-zero progress must rotate
        to the healthy candidate without burning the resume budget."""
        with tempfile.TemporaryDirectory() as tmp:
            ok, out = self._download(tmp, [self.die.url, self.ok.url])
            self.assertTrue(ok)
            self.assertEqual(out.read_bytes(), content_slice(0, TOTAL))

    def test_checkpoint_skips_completed_segments(self):
        """A 1/3-complete run (sidecar from an interrupted invocation) must
        skip segment 0 entirely - no request touches its offsets - and
        still produce byte-exact output."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "audio.m4s"
            seg0 = content_slice(0, SEG_SIZE)
            out.write_bytes(seg0 + b"\x00" * (TOTAL - SEG_SIZE))  # preallocated file
            audio_utils._bili_save_checkpoint(
                audio_utils._bili_progress_sidecar_path(out),
                "jrpdlite/test", TOTAL, SEG_SIZE, {0})
            ok, _ = self._download(tmp, [self.kill.url, self.ok.url])
            self.assertTrue(ok)
            self.assertEqual(out.read_bytes(), content_slice(0, TOTAL))
            all_starts = (
                [r[1] for r in self.kill.requests]
                + [r[1] for r in self.ok.requests]
                + [r[1] for r in self.die.requests]
                + [r[1] for r in self.trim.requests]
            )
            self.assertNotIn(0, all_starts, "completed segment 0 was re-requested")

    def test_probe_orders_full_range_host_first(self):
        """The probe must rank the Akamai-trim host (serves only 128 KiB of
        the 4 MiB request) below the healthy mirror and report the real
        total from Content-Range."""
        urls = [self.trim.url, self.ok.url]
        health = audio_utils._BiliHostHealth()
        ordered, total = audio_utils._bili_probe_candidates(urls, health)
        self.assertEqual(ordered[0], self.ok.url,
                         "full-range host must probe ahead of the trimming host")
        self.assertEqual(total, TOTAL)
        self.assertEqual(ordered[1], self.trim.url)


if __name__ == "__main__":
    unittest.main(verbosity=2)
