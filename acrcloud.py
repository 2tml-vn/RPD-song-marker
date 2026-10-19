"""
ACRCloud integration for JRPD marker system.
Provides audio fingerprinting and song identification via ACRCloud API.

``recognize()`` returns a result dict, ``None`` when the audio has no
match, or raises :class:`AcrQuotaExceededError` when the account hit a
limit (code 3003) — that exception is never converted to a silent None.
"""
import asyncio
import aiohttp
import os
import time
import hashlib
import hmac
import base64
import json
import re
import logging
from typing import Optional, Dict, Any

from config import ACR_CONFIG

logger = logging.getLogger("JRPD")


class AcrQuotaExceededError(Exception):
    """ACRCloud answered an account-level limit (code 3003 = requests exceeded).

    Raised (not swallowed into "no match") so sweeps can stop sending
    windows to a dead account and the UI can show a real status instead
    of a misleading silent result.
    """

    def __init__(self, code: int, msg: str = "") -> None:
        self.code = code
        self.msg = msg
        super().__init__(f"ACRCloud quota/limit exceeded (code {code}): {msg}")


# In-process stop-flag: once the endpoint confirms an account-level
# limit, further requests this run are pure waste (it is a plan-period
# limit — clicking again in a few minutes cannot change the answer).
# Plain RAM, resets when the process restarts, nothing saved anywhere.
_quota_exhausted = False


def quota_exhausted() -> bool:
    """True once code 3003 was confirmed this process (no new requests)."""
    return _quota_exhausted

# ACRCloud API endpoint
ENDPOINT = '/v1/identify'

# Module-level sessions for connection pooling, keyed by event loop.
# The ACR API is called from two different loops: the main asyncio.run()
# loop and the aiohttp server thread's loop (see handle_acr_identify).
# aiohttp binds a ClientSession/connector to its creating loop, so a single
# shared session raises "attached to a different loop" on use/close.
# Keep one session per loop instead of a single global.
_acr_sessions: Dict[int, "aiohttp.ClientSession"] = {}
_acr_session_loops: Dict[int, "asyncio.AbstractEventLoop"] = {}


def is_japanese(text):
    """
    Checks if a string contains Japanese characters (Hiragana, Katakana, or Kanji).
    """
    if not text: return False
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
    Flatten the most useful ACRCloud music fields into a single dict.

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


async def get_acr_session() -> aiohttp.ClientSession:
    """
    Get or create the shared ACRCloud aiohttp session for the *current*
    event loop. One session per loop: the main loop and the HTTP server
    thread's loop must not share a session (aiohttp binds the connector
    to its creating loop).
    """
    loop = asyncio.get_running_loop()
    key = id(loop)
    sess = _acr_sessions.get(key)
    if sess is None or sess.closed:
        sess = aiohttp.ClientSession()
        _acr_sessions[key] = sess
        _acr_session_loops[key] = loop
    return sess


async def close_acr_session():
    """Close ACRCloud session(s) (call on shutdown).

    Closes the current loop's session directly; sessions owned by other
    (e.g. server thread) loops are closed via run_coroutine_threadsafe on
    their owning loop so we never await a cross-loop close (which raises
    "attached to a different loop").
    """
    try:
        cur = asyncio.get_running_loop()
    except RuntimeError:
        cur = None  # type: ignore[assignment]
    for key, sess in list(_acr_sessions.items()):
        owner = _acr_session_loops.get(key)
        try:
            if sess.closed:
                continue
            if cur is not None and owner is not None and owner is not cur:
                # Wrong loop: schedule close on the owning loop instead of
                # awaiting here (awaiting would raise
                # "attached to a different loop"). Fire-and-forget: do not
                # block this loop waiting for the other one.
                try:
                    if not owner.is_closed():
                        asyncio.run_coroutine_threadsafe(sess.close(), owner)
                except Exception as e:
                    logger.debug(f"[ACR] Could not close session on owner loop: {e}")
                continue
            await sess.close()
        except RuntimeError as e:
            # Defensive: old aiohttp versions raise
            # "got Future ... attached to a different loop" here.
            if "different loop" in str(e) or "attached" in str(e):
                logger.debug(f"[ACR] Skipped cross-loop session close: {e}")
            else:
                logger.debug(f"[ACR] Error closing session: {e}")
        except Exception as e:
            logger.debug(f"[ACR] Error closing session: {e}")
        finally:
            _acr_sessions.pop(key, None)
            _acr_session_loops.pop(key, None)


async def recognize(file_path, access_key=None, access_secret=None, host=None) -> Optional[Dict[str, Any]]:
    """
    Identifies audio using ACRCloud's REST API.
    Returns a dict with 'title', 'en_title', 'artist' plus
    'detail' (flattened useful fields), 'raw' (full top music object),
    'candidates' (summary of all music candidates) and 'status'.
    Returns None if not found.
    """
    global _quota_exhausted
    key = access_key or ACR_CONFIG.get('access_key')
    secret = access_secret or ACR_CONFIG.get('access_secret')
    acr_host = host or ACR_CONFIG.get('host')

    # Check for missing credentials - return early
    if not key or not secret:
        logger.warning("[ACR] Missing ACRCloud credentials - check .env file")
        return None

    # Check for placeholder keys - return early
    if key == 'your-access-key-here' or key == 'YOUR_ACCESS_KEY':
        logger.warning("[ACR] Placeholder access key detected, skipping identification")
        return None

    # Fast-exit: once exhaustion is confirmed for this process, never
    # quietly re-ask (and never fake a "no match") until restart.
    if _quota_exhausted:
        raise AcrQuotaExceededError(3003, "quota already exhausted earlier in this process")

    http_method = "POST"
    http_uri = ENDPOINT
    data_type = "audio"
    signature_version = "1"
    timestamp = str(int(time.time()))

    string_to_sign = f"{http_method}\n{http_uri}\n{key}\n{data_type}\n{signature_version}\n{timestamp}"

    sign = hmac.new(secret.encode('ascii'), string_to_sign.encode('ascii'), digestmod=hashlib.sha1).digest()
    signature = base64.b64encode(sign).decode('ascii')

    url = f"http://{acr_host}{ENDPOINT}"

    try:
        session = await get_acr_session()
        
        # Read file content BEFORE the async request to avoid "I/O operation on closed file"
        file_size = os.path.getsize(file_path)
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        logger.debug(f"[ACR] Sending request to {url}, file size: {file_size} bytes")
        
        # Build multipart form data properly
        data = aiohttp.FormData()
        data.add_field('sample', file_content, filename='audio_sample.wav')
        data.add_field('sample_bytes', str(file_size))
        data.add_field('access_key', key)
        data.add_field('data_type', data_type)
        data.add_field('signature_version', signature_version)
        data.add_field('signature', signature)
        data.add_field('timestamp', timestamp)

        async with session.post(url, data=data) as response:
            res_text = await response.text()
            logger.debug(f"[ACR] Response status: {response.status}")
            logger.debug(f"[ACR] Response text: {res_text[:500] if res_text else '(empty)'}")
            
            result = json.loads(res_text)

            status = result.get('status', {})
            status_code = status.get('code', -1)
            logger.debug(f"[ACR] Status code: {status_code}, msg: {status.get('msg', 'unknown')}")

            if status_code == 3003:
                # Account-level limit ("requests limit exceeded, please
                # upgrade your account"): a plan-period limit. Surface it
                # + stop feeding the account in-process; retrying now
                # only burns windows.
                if not _quota_exhausted:
                    _quota_exhausted = True
                    logger.warning(
                        "[ACR] quota exceeded (code 3003): %s — ACR disabled until process restart",
                        status.get('msg', 'requests limit exceeded'),
                    )
                raise AcrQuotaExceededError(status_code, status.get('msg', ''))

            if status_code == 0:
                metadata = result.get('metadata', {})
                music_list = metadata.get('music', [])
                if not music_list:
                    return None
                music = music_list[0]

                main_title = music.get('title')
                if not main_title or main_title == 'Unknown Title':
                    # If we don't even have a main title, this is a failed identification
                    return None

                ext = music.get('external_metadata', {}) or {}

                # Try to find an English title in external metadata (Spotify/Deezer)
                en_title = None
                for source in ['spotify', 'deezer']:
                    source_data = ext.get(source, {}) or {}
                    t = (source_data.get('track', {}) or {}).get('name')
                    if t and not is_japanese(t):
                        en_title = t
                        break

                artist_list = music.get('artists', []) or []
                if not artist_list:
                    return None

                artist = ", ".join([a.get('name') for a in artist_list])

                if not main_title or not artist or artist.strip() == "":
                    return None

                return {
                    "title": main_title,
                    "en_title": en_title,
                    "artist": artist,
                    "detail": extract_track_detail(music, en_title=en_title),
                    "raw": music,
                    "candidates": [summarize_candidate(m) for m in music_list],
                    "status": {"code": status_code, "msg": status.get('msg', '')},
                }
    except AcrQuotaExceededError:
        # Propagate — never disguise quota exhaustion as "no match".
        raise
    except aiohttp.ClientError as e:
        logger.debug(f"[ACR] Network error: {e}")
    except json.JSONDecodeError as e:
        logger.debug(f"[ACR] JSON decode error: {e}")
    except OSError as e:
        logger.debug(f"[ACR] File error: {e}")
    except Exception as e:
        logger.debug(f"[ACR] Unexpected error: {e}")
    return None