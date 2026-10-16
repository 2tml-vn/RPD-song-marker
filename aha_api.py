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
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from curl_cffi import requests as cf_requests, CurlMime

logger = logging.getLogger("JRPD")

try:
    # Preferred: shared config (URL / timeout / enabled via env).
    from config import AHA_CONFIG  # type: ignore
except Exception:
    # Standalone fallback so `python aha_api.py snippet.mp3` works
    # outside the JRPD checkout (e.g. D:\\projects\\aha\\extracted).
    AHA_CONFIG = {
        "url": os.getenv("AHA_URL", "https://aha-music.com/identify"),
        "timeout": int(os.getenv("AHA_TIMEOUT", "30") or 30),
        "enabled": os.getenv("AHA_ENABLED", "1").strip().lower()
        not in ("0", "false", "no", "off", ""),
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


def _post_sync(mime: str, filename: str, file_path_str: str, url: str, timeout: int) -> Dict[str, Any]:
    """Blocking AHA identify call (runs inside ``asyncio.to_thread``)."""
    s = cf_requests.Session(impersonate="chrome124")
    try:
        try:
            # Warm-up: fetch session cookies like the browser client does.
            # Best-effort only — a warm-up failure must not fail the call.
            s.get("https://aha-music.com/", headers=HEADERS, timeout=timeout)
        except Exception as e:
            logger.debug(f"[AHA] Warm-up failed (continuing): {e}")

        mp = CurlMime()
        mp.addpart(name="sample", content_type=mime,
                   filename=filename, local_path=file_path_str)
        mp.addpart(name="marker", data="        ")

        r = s.post(url, headers=HEADERS, multipart=mp, timeout=timeout)
        r.raise_for_status()
        return r.json()
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
    except Exception as e:
        logger.debug(f"[AHA] Network error: {e}")
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
