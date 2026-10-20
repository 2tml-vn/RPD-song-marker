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
import time
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
SLOW_CHUNK = 16384       # /slow: streams the range in small chunks
SLOW_SLEEP = 0.03        # ...with a delay, so the download lasts ~0.35 s/seg


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
        if mode == "slow":
            # Streams the full range slowly in small chunks: gives the
            # live progress monitor several ticks mid-download instead of
            # finishing in milliseconds.
            self.send_response(206)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Range", f"bytes {start}-{end}/{cfg['total']}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            for off in range(0, len(data), SLOW_CHUNK):
                self.wfile.write(data[off:off + SLOW_CHUNK])
                time.sleep(SLOW_SLEEP)
            return
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
        cls.slow = _MockCdn("slow")

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.ok, cls.kill, cls.die, cls.trim, cls.slow):
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
        the range request) below the healthy mirror and report the real
        total from Content-Range."""
        urls = [self.trim.url, self.ok.url]
        health = audio_utils._BiliHostHealth()
        ordered, total = audio_utils._bili_probe_candidates(urls, health)
        self.assertEqual(ordered[0], self.ok.url,
                         "full-range host must probe ahead of the trimming host")
        self.assertEqual(total, TOTAL)
        self.assertEqual(ordered[1], self.trim.url)

    def test_progress_meter_counts_session_bytes(self):
        """The meter adds session bytes on a lock and reports them separate
        from the checkpoint base the fraction display is built on."""
        meter = audio_utils._BiliProgressMeter(base=65536)
        self.assertEqual(meter.snapshot(), (65536, 0))
        meter.add(131072)
        meter.add(1)
        self.assertEqual(meter.snapshot(), (65536, 131073))

    def test_effective_segment_size_scales_with_16_inflight(self):
        """A ~89 MB file must plan total/16 (~5.6 MB) segments with the new
        16 workers; a small file clamps up to the 4 MiB floor."""
        total = 89_000_000
        seg = audio_utils._bili_effective_segment_size(
            total, audio_utils._BILI_INFLIGHT)
        self.assertEqual(seg, total // audio_utils._BILI_INFLIGHT)
        self.assertGreaterEqual(seg, audio_utils._BILI_SEG_MIN)
        self.assertLessEqual(seg, audio_utils._BILI_SEG_MAX)
        small = audio_utils._bili_effective_segment_size(
            20_971_520, audio_utils._BILI_INFLIGHT)
        self.assertEqual(small, audio_utils._BILI_SEG_MIN)

    def test_live_progress_lines_and_summary_logged(self):
        """The segmented downloader must log live speed/ETA lines while a
        download is in flight plus a final downloaded/MB-s summary line -
        the 'looks hung' bug this guards against."""
        old_interval = audio_utils._BILI_PROGRESS_INTERVAL
        audio_utils._BILI_PROGRESS_INTERVAL = 0.05
        self.addCleanup(setattr, audio_utils,
                        "_BILI_PROGRESS_INTERVAL", old_interval)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertLogs(audio_utils.logger, level="INFO") as cm:
                ok, out = self._download(tmp, [self.slow.url, self.ok.url])
            self.assertTrue(ok)
            self.assertEqual(out.read_bytes(), content_slice(0, TOTAL))
        messages = [r.getMessage() for r in cm.records]
        progress = [m for m in messages
                    if "audio.m4s:" in m and "MB/s" in m]
        self.assertTrue(progress, f"no live progress line logged: {messages}")
        summary = [m for m in messages
                   if "downloaded" in m and "avg" in m]
        self.assertTrue(summary, f"no downloaded summary logged: {messages}")

    def test_failure_logs_incomplete_and_keeps_checkpoint(self):
        """A hopeless host (never completes a segment) must end with the
        'incomplete: X MB' line and the checkpoint sidecar on disk."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "audio.m4s"
            with self.assertLogs(audio_utils.logger, level="INFO") as cm:
                ok = audio_utils._bili_segmented_download(
                    [self.die.url], out, TOTAL, "jrpdlite/test",
                    segment_size=SEG_SIZE, tail_verify=4096,
                    slow_limit=3, min_progress=1024)
            self.assertFalse(ok)
            messages = [r.getMessage() for r in cm.records]
            self.assertTrue(
                any("incomplete" in m for m in messages),
                f"no incomplete line logged: {messages}")
            sidecar = audio_utils._bili_progress_sidecar_path(out)
            self.assertTrue(sidecar.exists(),
                            "checkpoint missing after a failed run")


if __name__ == "__main__":
    unittest.main(verbosity=2)
