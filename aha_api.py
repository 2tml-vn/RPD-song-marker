"""
AHA Music integration for JRPD marker system.
Provides song identification via the public AHA Music endpoint
(https://aha-music.com/identify), which fronts the same ACRCloud
fingerprint database — no API credentials required.

Conforms to the ``acrcloud.py`` workflow contract:

- ``async def recognize(file_path, timeout=None)`` returns a dict with
  ``title``, ``en_title``, ``artist`` plus ``detail`` (flattened useful
  fields), ``raw`` (full music object), ``candidates`` (summary list)
  and ``status`` — or ``None`` when there is no match.
  When the endpoint keeps answering HTTP 429 across all retry attempts,
  ``AhaRateLimitedError`` is raised (not swallowed) so sweeps can skip
  the remaining AHA windows and the UI can show "rate-limited".
- Same helper shapes (``is_japanese``, ``summarize_candidate``,
  ``extract_track_detail``) so callers (``identifier.py``, ``server.py``)
  and the results-panel modal can treat AHA and ACRCloud hits
  interchangeably.
- Blocking ``curl_cffi`` I/O runs in ``asyncio.to_thread`` so the
  aiohttp event loops are never blocked.
- Logging via the shared ``JRPD`` logger with an ``[AHA]`` prefix.

Helpers intentionally mirror ``acrcloud.py`` (rather than importing it)
so this file stays portable as a single-file script::

    python aha_api.py snippet.mp3

which prints the flat clean result::

    {"title": ..., "artist": ..., "album": ..., "release_date": ...,
     "label": ..., "isrc": ..., "score": ..., "acrid": ...}
"""

import asyncio
import json
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from curl_cffi import requests as cf_requests, CurlMime
from curl_cffi.requests.exceptions import HTTPError

logger = logging.getLogger("JRPD")


class AhaRateLimitedError(Exception):
    """AHA identify endpoint kept answering HTTP 429 through every retry.

    Raised (not swallowed) so per-sweep callers can stop re-firing AHA
    windows and surface a real "rate-limited" status instead of a
    misleading "no match".
    """

    def __init__(self, attempts: int, wait_seconds: float = 0.0) -> None:
        self.attempts = attempts
        self.wait_seconds = round(wait_seconds, 1)
        super().__init__(
            f"AHA rate-limited: HTTP 429 after {attempts} attempts "
            f"({self.wait_seconds:.1f}s total backoff)"
        )

try:
    # Preferred: shared config (URL / timeout / enabled via env).
    from config import AHA_CONFIG  # type: ignore
except Exception:
    # Standalone fallback so `python aha_api.py snippet.mp3` works
    # outside the JRPD checkout (e.g. D:\\projects\\aha\\extracted).
    AHA_CONFIG = {
        "url": os.getenv("AHA_URL", "https://aha-music.com/identify"),
        "timeout": int(os.getenv("AHA_TIMEOUT", "30") or 30),
        "connect_timeout": int(os.getenv("AHA_CONNECT_TIMEOUT", "8") or 8),
        "enabled": os.getenv("AHA_ENABLED", "1").strip().lower()
        not in ("0", "false", "no", "off", ""),
        "retry_attempts": int(os.getenv("AHA_RETRY_ATTEMPTS", "5") or 5),
        "retry_base_wait": float(os.getenv("AHA_RETRY_BASE_WAIT", "0.5") or 0.5),
    }

URL = AHA_CONFIG.get("url", "https://aha-music.com/identify")
HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://aha-music.com",
    "Referer": "https://aha-music.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

MIME = {".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".wav": "audio/wav",
        ".m4a": "audio/mp4", ".flac": "audio/flac", ".webm": "audio/webm"}

# Statuses worth retrying with exponential backoff — the same set shazamio's
# aiohttp_retry config retries ({500, 502, 503, 504, 429}).
_RETRIABLE_STATUSES = {429, 500, 502, 503, 504}


def is_japanese(text):
    """
    Checks if a string contains Japanese characters (Hiragana, Katakana, or Kanji).
    """
    if not text:
        return False
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text))


def _safe_name_list(items):
    """Extract 'name' from a list of dicts, skipping blanks."""
    out = []
    for it in items or []:
        if isinstance(it, dict):
            n = it.get('name')
            if n:
                out.append(n)
    return out


def summarize_candidate(music: Dict[str, Any]) -> Dict[str, Any]:
    """Compact summary of one music candidate (for logging / UI)."""
    if not isinstance(music, dict):
        return {}
    artists = _safe_name_list(music.get('artists', []))
    album = music.get('album', {}) or {}
    return {
        "title": music.get('title'),
        "artist": ", ".join(artists),
        "album": album.get('name'),
        "release_date": music.get('release_date'),
        "duration_ms": music.get('duration_ms'),
        "score": music.get('score'),
        "label": music.get('label'),
    }


def extract_track_detail(music: Dict[str, Any], en_title: Optional[str] = None) -> Dict[str, Any]:
    """
    Flatten the most useful music fields into a single dict.

    Covers: album, release_date, duration, score, label, genres,
    ISRC/UPC/ISWC, play offset + sample/db timing, and
    Spotify / Deezer / YouTube links.
    """
    if not isinstance(music, dict):
        return {}
    artists = _safe_name_list(music.get('artists', []))
    album = music.get('album', {}) or {}
    ext = music.get('external_metadata', {}) or {}
    ext_ids = music.get('external_ids', {}) or {}

    spotify = ext.get('spotify', {}) or {}
    spotify_track = spotify.get('track', {}) or {}
    spotify_id = spotify_track.get('id')
    spotify_url = None
    try:
        ext_urls = spotify_track.get('external_urls', {}) or {}
        spotify_url = ext_urls.get('spotify') or (f"https://open.spotify.com/track/{spotify_id}" if spotify_id else None)
    except Exception:
        spotify_url = f"https://open.spotify.com/track/{spotify_id}" if spotify_id else None

    deezer = ext.get('deezer', {}) or {}
    deezer_track = deezer.get('track', {}) or {}
    deezer_id = deezer_track.get('id')
    deezer_url = deezer_track.get('link') or (f"https://www.deezer.com/track/{deezer_id}" if deezer_id else None)

    youtube = ext.get('youtube', {}) or {}
    # youtube shape varies: {'vid': 'xxx'} or {'track': {'vid': ...}}
    yt_vid = youtube.get('vid')
    if not yt_vid and isinstance(youtube.get('track'), dict):
        yt_vid = youtube['track'].get('vid')
    youtube_url = f"https://youtu.be/{yt_vid}" if yt_vid else None

    genres = _safe_name_list(music.get('genres', []))

    duration_ms = music.get('duration_ms')
    duration_sec = None
    try:
        duration_sec = round(int(duration_ms) / 1000.0, 1) if duration_ms is not None else None
    except (ValueError, TypeError):
        duration_sec = None

    return {
        "title": music.get('title'),
        "artist": ", ".join(artists),
        "en_title": en_title,
        "album": album.get('name'),
        "release_date": music.get('release_date'),
        "duration_ms": duration_ms,
        "duration_sec": duration_sec,
        "score": music.get('score'),
        "label": music.get('label'),
        "genres": genres,
        "isrc": ext_ids.get('isrc'),
        "upc": ext_ids.get('upc'),
        "iswc": ext_ids.get('iswc'),
        "language": music.get('language'),
        "result_type": music.get('result_type'),
        "play_offset_ms": music.get('play_offset_ms'),
        "sample_begin_ms": music.get('sample_begin_time_offset_ms'),
        "sample_end_ms": music.get('sample_end_time_offset_ms'),
        "db_begin_ms": music.get('db_begin_time_offset_ms'),
        "db_end_time_offset_ms": music.get('db_end_time_offset_ms'),
        "spotify_track": spotify_track.get('name'),
        "spotify_id": spotify_id,
        "spotify_url": spotify_url,
        "deezer_track": deezer_track.get('name'),
        "deezer_id": deezer_id,
        "deezer_url": deezer_url,
        "youtube_vid": yt_vid,
        "youtube_url": youtube_url,
    }


def _retry_wait(attempt: int) -> float:
    """Exponential backoff wait for attempt N (1-based): base * 2^(N-1), with jitter.

    Mirrors shazamio's aiohttp_retry.ExponentialRetry ladder
    (start_timeout × factor^attempt), scaled up so HTTP-level waits are
    meaningful against AHA's per-IP window.
    """
    base = AHA_CONFIG.get("retry_base_wait", 0.5)
    try:
        base = float(base)
    except (TypeError, ValueError):
        base = 0.5
    wait = base * (2 ** (attempt - 1))
    wait = min(wait, 30.0)
    # Small jitter so overlapping sweeps don't march in lock-step.
    return wait + random.uniform(0.0, max(wait * 0.25, 0.05))


def _connect_timeout() -> int:
    """Connect-stage budget in seconds (AHA_CONNECT_TIMEOUT, default 8).

    Used purely for diagnostics: a connect-stage blackhole then surfaces as
    a fast, distinctly-labeled curl error instead of burning the whole total
    timeout.
    """
    ct = AHA_CONFIG.get("connect_timeout", 8)
    try:
        ct = int(ct)
    except (TypeError, ValueError):
        ct = 8
    return max(1, ct)


def _timeouts(tout: int) -> tuple:
    """curl_cffi timeout tuple ``(connect, read)`` preserving the old total.

    curl_cffi 0.14 maps ``(connect, read)`` to CONNECTTIMEOUT and
    ``TIMEOUT = connect + read``, so to keep the same 30s total budget the
    read leg must be ``tout - connect``. Always leaves >=2s of read budget.
    """
    ct = min(_connect_timeout(), max(1, int(tout) - 2))
    return (float(ct), max(2, int(tout) - ct))


def _probe_root(url: str) -> str:
    """Origin root of the identify URL (``https://aha-music.com/``)."""
    try:
        p = urlparse(url)
        root = f"{p.scheme}://{p.netloc}/"
        return root if root != "//" else "https://aha-music.com/"
    except Exception:
        return "https://aha-music.com/"


def _wedge_probe(s, probe_url: str) -> None:
    """One cheap GET probe fired once after the POST ladder has failed.

    The ladder only proves 'curl (28), 0 bytes' — no phase information. This
    probe classifies where the wedge lives:

    - 2xx answer      -> host edge is alive; the identify/POST path
                         (ACRCloud-backed backend) is what stalled.
    - HTTP 4xx/5xx    -> edge alive but tarpitting/erroring on the service.
    - same curl (28)  -> path/edge-level wedge: the whole host is mute.
    - fast curl (7/6) -> connect/DNS-stage failure (distinct label).

    Diagnostics only — never raises, so the original exception always
    propagates unchanged.
    """
    probe_timeouts = (max(2.0, _connect_timeout() / 2.0),
                      max(2.0, _connect_timeout() / 2.0))
    t0 = time.monotonic()
    try:
        r = s.get(probe_url, timeout=probe_timeouts)
        took = time.monotonic() - t0
        if 200 <= r.status_code < 300:
            verdict = "identify-backend stall (edge answers, POST path wedged)"
        else:
            verdict = "edge alive but service answering " \
                      f"HTTP {r.status_code} while POSTs wedge"
        logger.info(
            "[AHA] Wedge probe after POST ladder failure: GET %s -> HTTP %s "
            "in %.2fs — %s",
            probe_url, r.status_code, took, verdict,
        )
    except Exception as e:
        took = time.monotonic() - t0
        detail = str(e)
        if len(detail) > 160:
            detail = detail[:160] + "…"
        logger.info(
            "[AHA] Wedge probe after POST ladder failure: GET %s -> %s "
            "after %.2fs — host/path unreachable",
            probe_url, detail, took,
        )


def _post_sync(mime: str, filename: str, file_path_str: str, url: str, timeout: int) -> Dict[str, Any]:
    """Blocking AHA identify call (runs inside ``asyncio.to_thread``).

    Changes vs the pre-retry version:

    - The snippet is read fully into memory and uploaded as ``data=`` —
      no ``local_path``, so curl never keeps a file handle open after a
      dead upload (the cause of WinError 32 / locked ``seg_*.wav``).
    - Retriable statuses (HTTP 429 + 5xx, same set shazamio retries) are
      re-sent with an exponential backoff ladder
      (``AHA_RETRY_BASE_WAIT * 2^attempt`` + jitter, honoring a
      ``Retry-After`` header when present).

    Raises:
        AhaRateLimitedError: HTTP 429 on every attempt — propagate so
            sweeps can skip AHA and the UI can show "rate-limited".
        HTTPError: other non-2xx statuses (unchanged behavior).
        Exception: last transport error when attempts exhaust.
    """
    try:
        attempts = max(1, int(AHA_CONFIG.get("retry_attempts", 5)))
    except (TypeError, ValueError):
        attempts = 5

    # Read snippet bytes BEFORE any request — the same buffer is reused
    # for every attempt and no file handle outlives the call.
    with open(file_path_str, "rb") as f:
        content = f.read()

    s = cf_requests.Session(impersonate="chrome124")
    total_backoff = 0.0
    raised: Optional[BaseException] = None
    last_status: Optional[int] = None
    probe_url = _probe_root(url)
    req_timeouts = _timeouts(timeout)
    try:
        try:
            # Warm-up: fetch session cookies like the browser client does.
            # Best-effort only — a warm-up failure must not fail the call.
            wu_t0 = time.monotonic()
            s.get(probe_url, headers=HEADERS, timeout=req_timeouts)
            logger.debug(
                "[AHA] Warm-up GET %s OK in %.2fs", probe_url,
                time.monotonic() - wu_t0,
            )
        except Exception as e:
            # INFO (not DEBUG): a wedge that starts between calls is only
            # visible here, and it is exactly what flags the episode start.
            logger.info(f"[AHA] Warm-up GET {probe_url} failed (continuing): {e}")

        for attempt in range(1, attempts + 1):
            # Fresh mime per attempt: curl consumes the multipart body.
            mp = CurlMime()
            mp.addpart(name="sample", content_type=mime,
                       filename=filename, data=content)
            mp.addpart(name="marker", data="        ")
            try:
                r = s.post(url, headers=HEADERS, multipart=mp,
                           timeout=req_timeouts)
            except Exception as e:
                # Transport failure (e.g. H2 stream cut mid-upload).
                raised = e
                last_status = None
                if attempt >= attempts:
                    break
                wait = _retry_wait(attempt)
                total_backoff += wait
                logger.info(
                    f"[AHA] Transport error (attempt {attempt}/{attempts}): {e} — retrying in {wait:.1f}s"
                )
                time.sleep(wait)
                continue

            if r.status_code in _RETRIABLE_STATUSES:
                last_status = r.status_code
                raised = None
                if attempt >= attempts:
                    break
                # Honor server-provided Retry-After when present.
                ra = r.headers.get("Retry-After") if r.headers else None
                try:
                    wait = min(float(ra), 60.0) if ra else _retry_wait(attempt)
                except (TypeError, ValueError):
                    wait = _retry_wait(attempt)
                total_backoff += wait
                logger.info(
                    "[AHA] HTTP %s (attempt %d/%d) — retrying in %.1fs",
                    r.status_code, attempt, attempts, wait,
                )
                time.sleep(wait)
                continue

            r.raise_for_status()
            return r.json()

        # Attempt ladder exhausted without a usable response.
        if last_status == 429:
            logger.warning(
                "[AHA] rate-limited: HTTP 429 on all %d attempts (%.1fs total backoff) — reporting rate_limited",
                attempts, total_backoff,
            )
            raise AhaRateLimitedError(attempts, total_backoff)
        if raised is not None:
            # Transport-level failure: classify the wedge with one cheap GET
            # before propagating (diagnostics only; never masks the error).
            _wedge_probe(s, probe_url)
            raise raised
        if last_status is not None:
            raise HTTPError(f"HTTP Error {last_status}", 0, None)
        raise RuntimeError("[AHA] identify attempts exhausted without a response")
    finally:
        try:
            s.close()
        except Exception:
            pass


async def recognize(file_path, timeout=None) -> Optional[Dict[str, Any]]:
    """
    Identifies audio using the AHA Music endpoint.
    Returns a dict with 'title', 'en_title', 'artist' plus
    'detail' (flattened useful fields), 'raw' (full music object),
    'candidates' (summary list) and 'status'.
    Returns None if not found.

    Raises AhaRateLimitedError when the endpoint answers HTTP 429 on
    every retry attempt (never converted to a silent None / "no match").
    """
    if not AHA_CONFIG.get('enabled', True):
        logger.debug("[AHA] Disabled via config (AHA_ENABLED=0), skipping")
        return None

    cfg_timeout = AHA_CONFIG.get('timeout', 30)
    try:
        cfg_timeout = int(cfg_timeout)
    except (TypeError, ValueError):
        cfg_timeout = 30
    tout = timeout or cfg_timeout
    url = AHA_CONFIG.get('url', URL)

    # Stat the file BEFORE the request (same habit as acrcloud.py).
    try:
        p = Path(file_path)
        file_size = p.stat().st_size
    except OSError as e:
        logger.debug(f"[AHA] File error: {e}")
        return None
    if file_size == 0:
        logger.debug("[AHA] Empty audio file, skipping")
        return None

    mime = MIME.get(p.suffix.lower(), "audio/mpeg")
    filename = "recording" + (p.suffix if p.suffix else ".mp3")
    logger.debug(f"[AHA] Sending request to {url}, file size: {file_size} bytes")

    try:
        payload = await asyncio.to_thread(_post_sync, mime, filename, str(p), url, tout)
    except AhaRateLimitedError:
        # Propagate: sweeps catch this to skip remaining AHA windows and
        # the UI reports "rate-limited" instead of a fake "no match".
        raise
    except Exception as e:
        logger.warning(f"[AHA] Network error after retries: {e}")
        return None

    try:
        body = payload.get("data") if isinstance(payload, dict) else None
        if not body or "title" not in body:
            logger.debug("[AHA] No match in response")
            return None

        main_title = body.get('title')
        if not main_title or main_title == 'Unknown Title':
            # If we don't even have a main title, this is a failed identification
            return None

        ext = body.get('external_metadata', {}) or {}

        # Try to find an English title in external metadata (Spotify/Deezer)
        en_title = None
        for source in ['spotify', 'deezer']:
            source_data = ext.get(source, {}) or {}
            t = (source_data.get('track', {}) or {}).get('name')
            if t and not is_japanese(t):
                en_title = t
                break

        artist_list = body.get('artists', []) or []
        if not artist_list:
            return None

        artist = ", ".join([a.get('name') for a in artist_list if isinstance(a, dict) and a.get('name')])

        if not main_title or not artist or artist.strip() == "":
            return None

        return {
            "title": main_title,
            "en_title": en_title,
            "artist": artist,
            "detail": extract_track_detail(body, en_title=en_title),
            "raw": body,
            "candidates": [summarize_candidate(body)],
            "status": {"code": 0, "msg": "ok"},
        }
    except (AttributeError, TypeError, ValueError) as e:
        logger.debug(f"[AHA] Response parse error: {e}")
    except Exception as e:
        logger.debug(f"[AHA] Unexpected error: {e}")
    return None


def clean_result(result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Flatten a :func:`recognize` result to the portable clean shape used by
    the ``python aha_api.py snippet.mp3`` CLI::

        {"title", "artist", "album", "release_date",
         "label", "isrc", "score", "acrid"}

    (``acrid`` lives on the raw music object, not in ``detail``.)
    Returns None when there is no match.
    """
    if not result:
        return None
    detail = result.get('detail') or {}
    raw = result.get('raw') or {}
    return {
        "title": detail.get('title'),
        "artist": detail.get('artist'),
        "album": detail.get('album'),
        "release_date": detail.get('release_date'),
        "label": detail.get('label'),
        "isrc": detail.get('isrc'),
        "score": detail.get('score'),
        "acrid": raw.get('acrid'),
    }


def recognize_sync(file_path, timeout=None) -> Optional[Dict[str, Any]]:
    """
    Blocking wrapper around :func:`recognize` for sync callers and the CLI.
    Returns the flat clean shape (see :func:`clean_result`).
    Do NOT call from inside a running event loop — await ``recognize()`` instead.
    """
    return clean_result(asyncio.run(recognize(file_path, timeout=timeout)))


# Backward-compatible sync aliases (pre-workflow API).
def identify(path, timeout=None) -> Dict[str, Any]:
    """Blocking raw identify call (legacy). Prefer ``await recognize()``."""
    tout = timeout or AHA_CONFIG.get('timeout', 30)
    url = AHA_CONFIG.get('url', URL)
    p = Path(path)
    mime = MIME.get(p.suffix.lower(), "audio/mpeg")
    filename = "recording" + (p.suffix if p.suffix else ".mp3")
    return _post_sync(mime, filename, str(p), url, int(tout))


def recognize_legacy(path, timeout=None) -> Optional[Dict[str, Any]]:
    """Blocking flat recognize (legacy). Prefer :func:`recognize_sync`."""
    return recognize_sync(path, timeout=timeout)


if __name__ == "__main__":
    import sys

    def _usage():
        print(f"Usage: python {Path(sys.argv[0]).name} <audio_file>", file=sys.stderr)

    args = [a for a in sys.argv[1:] if a not in ("-h", "--help")]
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        _usage()
        raise SystemExit(0)
    if len(args) != 1:
        _usage()
        raise SystemExit(2)
    try:
        flat = recognize_sync(args[0])
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
    except RuntimeError as e:
        # e.g. called from inside a running event loop
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(flat, indent=2, ensure_ascii=False))
