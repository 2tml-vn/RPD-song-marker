"""
HTTP server for JRPD marker system.
Handles communication between browser userscript and Python backend.

Uses aiohttp for async I/O, eliminating thread overhead and improving concurrency.
"""
import json
import os
import logging
import subprocess
import re
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

from aiohttp import web

from config import PORT, MISIDENTIFIED_SONGS_FILE, MISSED_SONGS_FILE, SONG_OVERRIDES_FILE, SONG_NAME_PARENS_EXCEPTIONS_FILE, EDITOR_PATH, RUNS_DIR
from audio_utils import format_display_name
from song_db import SONG_OVERRIDES, MISSED_SONGS, SONG_NAME_PARENS_EXCEPTIONS, save_song_overrides, load_song_overrides

# Note: load_song_overrides() is called by the main script, not here

logger = logging.getLogger("JRPD")

# Pre-compiled regex patterns for performance
_TIMESTAMP_PATTERN = re.compile(r'^(\d+:\d{2}(?::\d{2})?)\s?(.*)')


def update_results_line(filepath: Path, ts: str, new_content: str) -> bool:
    """
    Update a specific timestamp line in the results file.
    If the timestamp does not exist yet, inserts it in sorted order.
    If the file does not exist, creates it.
    
    Args:
        filepath: Path to the results.txt file
        ts: Timestamp to find and update (e.g., "1:30")
        new_content: New content to write after the timestamp
        
    Returns:
        True if the line was written, False on OS error
    """
    try:
        import shared_utils
        filepath.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()

        new_lines = []
        replaced = False
        for line in lines:
            stripped = line.rstrip('\n').rstrip('\r')
            m = _TIMESTAMP_PATTERN.match(stripped)
            if m and m.group(1) == ts and not replaced:
                new_lines.append(f"{ts} {new_content}\n")
                replaced = True
            else:
                new_lines.append(line if line.endswith('\n') else line + '\n')

        if not replaced:
            new_lines.append(f"{ts} {new_content}\n")
            def _get_ts(l):
                m = _TIMESTAMP_PATTERN.match(l.strip())
                return shared_utils.parse_ts(m.group(1)) if m else 0.0
            new_lines.sort(key=_get_ts)

        with open(filepath, "w", encoding="utf-8", newline='') as f:
            f.writelines(new_lines)
        return True
    except OSError as e:
        logger.warning(f"Error updating results line in {filepath}: {e}")
        return False



class JsonFileCache:
    """
    Simple JSON file cache with modification time checks.
    Avoids redundant disk I/O by caching file contents and only re-reading when modified.
    """
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._mtimes: Dict[str, float] = {}

    def get(self, filepath: Path) -> Optional[Dict[str, Any]]:
        """
        Get JSON data from cache or read from file if not cached or modified.
        Returns None if file doesn't exist or can't be parsed.
        """
        try:
            if not filepath.exists():
                return None

            current_mtime = filepath.stat().st_mtime
            cache_key = str(filepath)

            if cache_key in self._cache and self._mtimes.get(cache_key) == current_mtime:
                return self._cache[cache_key]

            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._cache[cache_key] = data
            self._mtimes[cache_key] = current_mtime
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"[CACHE] Error reading {filepath}: {e}")
            return None

    def invalidate(self, filepath: Path):
        """Invalidate cache entry for a file."""
        cache_key = str(filepath)
        self._cache.pop(cache_key, None)
        self._mtimes.pop(cache_key, None)


# Global file cache instance
_file_cache = JsonFileCache()


class ServerState:
    """
    Container for runtime server state.
    Encapsulates all mutable state for the HTTP server.
    """
    def __init__(self):
        self.main_loop = None
        self.mark_queue = None
        self.selection_queue = None
        self.current_seek_ts = -1
        self.cleanup_candidates: List[str] = []
        self.results: Dict[str, str] = {}
        self.is_finished = False
        self.is_session_done = False
        self.results_file_path: Optional[str] = None
        self.review_done_event = None
        self.review_done_kind: Optional[str] = None
        self.audio_path: Optional[str] = None
        self.snippets_dir: Optional[str] = None
        self.flagged_ts = set()

    def reset(self):
        """Reset state for a new session."""
        self.current_seek_ts = -1
        self.cleanup_candidates = []
        self.results = {}
        self.is_finished = False
        self.is_session_done = False
        self.flagged_ts = set()
        self.review_done_kind = None


# Global state instance
state = ServerState()


def _cors_headers():
    """Return CORS headers for responses."""
    return {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
    }


async def _json_response(data: Dict[str, Any], status: int = 200) -> web.Response:
    """Create a JSON response with proper headers."""
    return web.json_response(
        data,
        status=status,
        headers={
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
        }
    )


async def _status_response(status: str = "ok", message: Optional[str] = None) -> web.Response:
    """Create a simple status response."""
    response = {"status": status}
    if message:
        response["msg"] = message
    return await _json_response(response)


async def handle_options(request: web.Request) -> web.Response:
    """Handle CORS preflight requests."""
    return web.Response(headers=_cors_headers())


async def handle_add_mark(request: web.Request) -> web.Response:
    """Handle /add_mark endpoint."""
    try:
        ts = request.query.get('ts', '0')
        if state.main_loop and state.mark_queue:
            state.main_loop.call_soon_threadsafe(state.mark_queue.put_nowait, ts)
        return await _status_response("queued")
    except Exception as e:
        logger.error(f"Error in add_mark: {e}")
        return await _status_response("error", str(e))


async def handle_status(request: web.Request) -> web.Response:
    """Handle /status endpoint."""
    try:
        # Determine status message
        status_msg = ""
        if state.is_session_done:
            status_msg = "All identified! Finishing..."
        elif state.is_finished:
            processing_count = sum(1 for v in state.results.values() if v == "Processing...")
            if processing_count > 0:
                status_msg = f"Still identifying {processing_count} songs..."
            else:
                unidentified_count = sum(1 for v in state.results.values() if v == "Unidentified")
                if unidentified_count > 0:
                    status_msg = f"Starting cleanup for {unidentified_count} gaps"
                else:
                    status_msg = "All identified! Finishing..."

        import shared_utils
        response = {
            "seek_ts": state.current_seek_ts,
            "candidates": state.cleanup_candidates,
            "status_msg": status_msg,
            "marks": sorted(state.results.keys(), key=shared_utils.parse_ts),
            "is_review_mode": state.is_session_done
        }
        return await _json_response(response)
    except Exception as e:
        logger.error(f"Error in status: {e}")
        return await _status_response("error", str(e))


async def handle_results_file(request: web.Request) -> web.Response:
    """Handle /results_file endpoint."""
    result = {"lines": [], "mtime": 0}
    try:
        if state.results_file_path and Path(state.results_file_path).exists():
            result["mtime"] = os.path.getmtime(state.results_file_path)
            with open(state.results_file_path, "r", encoding="utf-8") as f:
                result["lines"] = [line.rstrip('\n').rstrip('\r') for line in f.readlines()]
            logger.debug(f"[RESULTS_FILE] Read {len(result['lines'])} lines from {state.results_file_path}")
        elif state.results:
            # Fallback to in-memory state.results when results.txt has not been flushed yet
            import shared_utils
            result["lines"] = [
                f"{m} {shared_utils.format_song_entry(state.results[m]) if state.results[m] not in ('Unidentified', 'Processing...') else (state.results[m] if state.results[m] == 'Processing...' else '')}".rstrip()
                for m in sorted(state.results.keys(), key=shared_utils.parse_ts)
            ]
            result["mtime"] = 1.0
            logger.debug(f"[RESULTS_FILE] Generated {len(result['lines'])} lines from in-memory results")
        else:
            logger.debug(f"[RESULTS_FILE] No results available yet")
    except OSError as e:
        logger.warning(f"[RESULTS_FILE] Error reading: {e}")
    except Exception as e:
        logger.warning(f"[RESULTS_FILE] Unexpected error: {e}")

    return await _json_response(result)


async def handle_review_done(request: web.Request) -> web.Response:
    """Handle /review_done endpoint - opens results in configured editor."""
    if state.results_file_path:
        try:
            results_path = Path(state.results_file_path)
            if results_path.exists():
                if os.path.exists(EDITOR_PATH):
                    subprocess.Popen([EDITOR_PATH, str(results_path)])
                    logger.info(f"[OPEN] results.txt opened in editor: {EDITOR_PATH}")
                else:
                    subprocess.Popen(f'start notepad++ "{results_path}"', shell=True)
                    logger.info("[OPEN] results.txt opened via notepad++ command")
        except OSError as e:
            logger.warning(f"[OPEN] Could not open results in editor: {e}")
        except Exception as e:
            logger.warning(f"[OPEN] Unexpected error: {e}")

    state.review_done_kind = "done"
    if state.main_loop and state.review_done_event:
        state.main_loop.call_soon_threadsafe(state.review_done_event.set)
    return await _status_response()


async def handle_close_review(request: web.Request) -> web.Response:
    """Handle /close_review endpoint."""
    state.review_done_kind = "close"
    if state.main_loop and state.review_done_event:
        state.main_loop.call_soon_threadsafe(state.review_done_event.set)
    return await _status_response()


async def handle_song_lists(request: web.Request) -> web.Response:
    """Handle /song_lists endpoint."""
    result = {"misidentified": [], "missed": [], "songs": []}
    try:
        # Use cached file reads to avoid redundant I/O
        misident_data = _file_cache.get(MISIDENTIFIED_SONGS_FILE)
        if misident_data:
            for key in sorted(misident_data.keys(), key=lambda x: x.lower()):
                data = misident_data[key]
                display = format_display_name(key, data.get('intl'), data.get('artist_orig'), data.get('artist_intl'))
                result["misidentified"].append({"display": display, "key": key})

        missed_data = _file_cache.get(MISSED_SONGS_FILE)
        if missed_data:
            for key in sorted(missed_data.keys(), key=lambda x: x.lower()):
                data = missed_data[key]
                display = format_display_name(key, data.get('intl'), data.get('artist_orig'), data.get('artist_intl'))
                result["missed"].append({"display": display, "key": key})

        songs_data = _file_cache.get(SONG_OVERRIDES_FILE)
        if songs_data:
            for key in sorted(songs_data.keys(), key=lambda x: x.lower()):
                data = songs_data[key]
                # Skip discarded songs
                if data.get('discard'):
                    continue
                display = format_display_name(key, data.get('intl'), data.get('artist_orig'), data.get('artist_intl'))
                result["songs"].append({
                    "display": display,
                    "key": key,
                    "intl": data.get('intl', ''),
                    "artist_orig": data.get('artist_orig', ''),
                    "artist_intl": data.get('artist_intl', '')
                })
    except Exception as e:
        logger.warning(f"[SONG_LISTS] Unexpected error: {e}")

    return await _json_response(result)


async def handle_update_result(request: web.Request) -> web.Response:
    """Handle /update_result endpoint."""
    ts = request.query.get('ts')
    song = request.query.get('song')
    old_song = request.query.get('old_song')

    result = {"status": "ok", "replaced": False, "actions": []}

    if not ts or song is None or not state.results_file_path:
        result["status"] = "error"
        result["msg"] = "missing params"
        return await _json_response(result)

    try:
        logger.info(f"[UPDATE_RESULT] Looking for timestamp: '{ts}'")
        canonical, _ = _split_flag_marker(song)
        replaced = update_results_line(Path(state.results_file_path), ts, canonical)
        
        result["replaced"] = replaced
        if replaced:
            result["actions"].append("updated_results")
        # Keep in-memory results in sync so the next save_state() (triggered by
        # the next mark or identification) does not revert this edit.
        state.results[ts] = canonical
        # Assigning (or blanking) a song is an explicit fix: clear any manual-review flag
        state.flagged_ts.discard(ts)
        logger.info(f"[UPDATE_RESULT] {ts} -> {canonical}")

    except OSError as e:
        logger.warning(f"[UPDATE_RESULT] File error: {e}")
        result["status"] = "error"
        result["msg"] = str(e)
    except Exception as e:
        logger.warning(f"[UPDATE_RESULT] Unexpected error: {e}")
        result["status"] = "error"
        result["msg"] = str(e)

    return await _json_response(result)


async def handle_add_song_and_update(request: web.Request) -> web.Response:
    """Handle /add_song_and_update endpoint - always saves to songs.json."""
    ts = request.query.get('ts')
    old_song = request.query.get('old_song')
    new_song_key = request.query.get('key')
    intl = request.query.get('intl', '')
    artist_orig = request.query.get('artist_orig', '')
    artist_intl = request.query.get('artist_intl', '')

    result = {"status": "ok", "actions": []}

    if not ts or not new_song_key:
        return await _json_response({"status": "error", "msg": "missing ts or key"})

    try:
        # 1. Save new song to songs.json (merge with existing entry if present)
        song_entry = SONG_OVERRIDES.get(new_song_key, {})
        if intl:
            song_entry['intl'] = intl
        if artist_orig:
            song_entry['artist_orig'] = artist_orig
        if artist_intl:
            song_entry['artist_intl'] = artist_intl
        SONG_OVERRIDES[new_song_key] = song_entry
        save_song_overrides()
        result["actions"].append("saved_to_songs")
        logger.info(f"[ADD_SONG] Added to songs.json: {new_song_key}")

        # 2. Update results.txt if results_file_path is configured
        if state.results_file_path:
            new_song_display = format_display_name(new_song_key, intl or None, artist_orig or None, artist_intl or None)
            replaced = update_results_line(Path(state.results_file_path), ts, new_song_display)
            
            if replaced:
                result["actions"].append("updated_results")
            # Keep in-memory results in sync so save_state() preserves the edit
            state.results[ts] = new_song_display
            # Assigning a new song is an explicit fix: clear any manual-review flag
            state.flagged_ts.discard(ts)
            logger.info(f"[ADD_SONG] Updated results.txt: {ts} -> {new_song_display}")

    except OSError as e:
        logger.warning(f"[ADD_SONG] File error: {e}")
        result["status"] = "error"
        result["msg"] = str(e)
    except Exception as e:
        logger.warning(f"[ADD_SONG] Unexpected error: {e}")
        result["status"] = "error"
        result["msg"] = str(e)

    return await _json_response(result)


async def handle_review_seek(request: web.Request) -> web.Response:
    """Handle /review_seek endpoint."""
    ts = request.query.get('ts')
    if ts is not None:
        try:
            state.current_seek_ts = int(float(ts))
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid seek timestamp: {ts} - {e}")
    return await _status_response()


async def handle_select(request: web.Request) -> web.Response:
    """Handle /select endpoint."""
    choice = request.query.get('choice')
    if choice and state.main_loop and state.selection_queue:
        state.main_loop.call_soon_threadsafe(state.selection_queue.put_nowait, choice)
    return await _status_response()


async def handle_get_song_data(request: web.Request) -> web.Response:
    """Handle /get_song_data endpoint."""
    key = request.query.get('key')

    if not key:
        return await _json_response({"error": "missing key"}, status=400)

    if key in SONG_OVERRIDES:
        result = SONG_OVERRIDES[key].copy()
    else:
        # Return empty dict for missing keys
        result = {}

    return await _json_response(result)


async def handle_update_song_vars(request: web.Request) -> web.Response:
    """Handle /update_song_vars endpoint."""
    try:
        # Parse POST data for updating song variables
        post_data = await request.post()

        song_key = post_data.get('key')

        # DEBUG: Log incoming parameters
        logger.info(f"[UPDATE_SONG_VARS] DEBUG: Received request")
        logger.info(f"[UPDATE_SONG_VARS] DEBUG: song_key='{song_key}'")
        for _f in ('intl', 'artist_orig', 'artist_intl', 'info', 'remap', 'discard', 'see_artist', 'intl_override'):
            logger.info(f"[UPDATE_SONG_VARS] DEBUG: {_f}='{post_data.get(_f, '')}'")
        logger.info(f"[UPDATE_SONG_VARS] DEBUG: SONG_OVERRIDES keys count={len(SONG_OVERRIDES)}")
        logger.info(f"[UPDATE_SONG_VARS] DEBUG: song_key in SONG_OVERRIDES: {song_key in SONG_OVERRIDES}")

        result = {"status": "ok", "actions": []}

        if not song_key:
            result = {"status": "error", "msg": "song key is required"}
            return await _json_response(result)

        def _is_truthy(v) -> bool:
            return str(v or '').strip().lower() in ('1', 'true', 'on', 'yes', 'checked')

        # Update the song in SONG_OVERRIDES - only store non-empty fields.
        # Empty inputs mean "no value": remove the key instead of persisting ""
        # so untouched fields never override/pollute the entry. Fields absent
        # from the POST are left untouched (partial-update safe).
        text_fields = ('intl', 'artist_orig', 'artist_intl', 'info', 'remap')
        bool_fields = ('discard', 'see_artist', 'intl_override')
        vals = {}
        for field in text_fields:
            if field in post_data:
                vals[field] = (post_data.get(field) or '').strip()
        bool_vals = {}
        for field in bool_fields:
            if field in post_data:
                bool_vals[field] = _is_truthy(post_data.get(field))
        entry = SONG_OVERRIDES.get(song_key)
        if entry is None:
            # Don't create a new entry when all inputs are empty —
            # untouched fields must not materialize as "" or {}.
            if not any(vals.values()) and not any(bool_vals.values()):
                logger.info(f"[UPDATE_SONG_VARS] No fields to store for new key: {song_key} (skipped)")
            else:
                entry = SONG_OVERRIDES.setdefault(song_key, {})
                for field, val in vals.items():
                    if val:
                        entry[field] = val
                for field, on in bool_vals.items():
                    if on:
                        entry[field] = True
        else:
            for field, val in vals.items():
                if val:
                    entry[field] = val
                else:
                    entry.pop(field, None)
            for field, on in bool_vals.items():
                if on:
                    entry[field] = True
                else:
                    entry.pop(field, None)

        save_song_overrides()
        result["actions"].append(f"updated_song: {song_key}")
        logger.info(f"[UPDATE_SONG_VARS] Updated song: {song_key}")

        # Also update results.txt if it exists
        if state.results_file_path and Path(state.results_file_path).exists():
            # Get the updated song data
            song_data = SONG_OVERRIDES.get(song_key, {})
            new_display = format_display_name(
                song_key,
                song_data.get('intl'),
                song_data.get('artist_orig'),
                song_data.get('artist_intl'),
                song_data.get('info')
            )

            # Read and update results.txt
            with open(state.results_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            new_lines = []
            updated_count = 0
            for line in lines:
                stripped = line.rstrip('\n').rstrip('\r')
                # Check if this line contains the song key
                if song_key in stripped:
                    # Extract timestamp if present
                    m = _TIMESTAMP_PATTERN.match(stripped)
                    if m:
                        ts = m.group(1)
                        # Preserve any manual-review flag on this row
                        _, was_flagged = _split_flag_marker(m.group(2) or "")
                        new_lines.append(f"{ts} {new_display} {FLAG_MARKER}\n" if was_flagged else f"{ts} {new_display}\n")
                        if was_flagged:
                            state.flagged_ts.add(ts)
                        updated_count += 1
                        # Mirror into in-memory results so save_state() preserves it
                        state.results[ts] = new_display
                        logger.info(f"[UPDATE_SONG_VARS] Updated results.txt: {ts} -> {new_display}")
                    else:
                        new_lines.append(f"{new_display}\n")
                        updated_count += 1
                else:
                    new_lines.append(line if line.endswith('\n') else line + '\n')

            if updated_count > 0:
                with open(state.results_file_path, "w", encoding="utf-8", newline='') as f:
                    f.writelines(new_lines)
                result["actions"].append(f"updated_results:{updated_count}")
                logger.info(f"[UPDATE_SONG_VARS] Updated {updated_count} lines in results.txt")

        # DEBUG: Log after update
        logger.info(f"[UPDATE_SONG_VARS] DEBUG: After update - SONG_OVERRIDES['{song_key}'] = {SONG_OVERRIDES.get(song_key, 'NOT FOUND')}")
        logger.info(f"[UPDATE_SONG_VARS] DEBUG: SONG_OVERRIDES_FILE = {SONG_OVERRIDES_FILE}")

        return await _json_response(result)

    except Exception as e:
        logger.warning(f"[UPDATE_SONG_VARS] Unexpected error: {e}")
        result = {"status": "error", "msg": str(e)}
        return await _json_response(result)


# Trailing marker for rows flagged for manual review in results.txt
FLAG_MARKER = "🚩"
_FLAG_RE = re.compile(r'\s*🚩\s*$')


def _split_flag_marker(content: str):
    """
    Split a trailing 🚩 flag marker from result line content.

    Returns:
        Tuple of (canonical_content, was_flagged)
    """
    if not content:
        return "", False
    stripped = content.strip()
    canonical = _FLAG_RE.sub('', stripped)
    if canonical != stripped:
        return canonical.strip(), True
    return stripped, False


def rebuild_flags_from_file() -> int:
    """
    Rebuild state.flagged_ts by scanning results.txt for trailing 🚩 markers.
    Also strips any markers that leaked into in-memory results values.

    Returns:
        Number of flagged timestamps
    """
    state.flagged_ts.clear()
    for k in list(state.results.keys()):
        v = state.results[k]
        if isinstance(v, str):
            canonical, was_flagged = _split_flag_marker(v)
            if was_flagged:
                state.results[k] = canonical
                state.flagged_ts.add(k)
    try:
        if state.results_file_path:
            p = Path(state.results_file_path)
            if p.exists():
                with open(p, "r", encoding="utf-8") as f:
                    for raw in f.read().splitlines():
                        m = _TIMESTAMP_PATTERN.match(raw.strip())
                        if m:
                            _, was_flagged = _split_flag_marker(m.group(2) or "")
                            if was_flagged:
                                state.flagged_ts.add(m.group(1))
    except OSError as e:
        logger.warning(f"[FLAGS] Error scanning results file: {e}")
    return len(state.flagged_ts)


_AUDIO_EXTS = ('m4a', 'opus', 'webm', 'mp3', 'mp4', 'ogg', 'wav', 'mka')


def _find_audio_file() -> Optional[Path]:
    """Locate the downloaded audio file for the current session."""
    try:
        if state.audio_path:
            p = Path(state.audio_path)
            if p.exists():
                return p
        if state.results_file_path:
            parent = Path(state.results_file_path).parent
            for ext in _AUDIO_EXTS:
                candidate = parent / f"audio.{ext}"
                if candidate.exists():
                    return candidate
        if RUNS_DIR.exists():
            candidates = sorted(
                RUNS_DIR.glob("*/audio.*"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for candidate in candidates:
                if candidate.suffix.lower().lstrip('.') in _AUDIO_EXTS:
                    return candidate
    except OSError as e:
        logger.warning(f"[ACR_IDENTIFY] Error locating audio file: {e}")
    return None


async def handle_acr_identify(request: web.Request) -> web.Response:
    """Handle /acr_identify endpoint - re-identify a single row with ACRCloud.

    Query params:
        ts: Timestamp of the row to identify (e.g. "1:30")
    """
    ts = request.query.get('ts')
    if not ts:
        return await _json_response({"status": "error", "msg": "missing ts"})

    try:
        import shared_utils
        current_sec = shared_utils.parse_ts(ts)
    except Exception as e:
        logger.warning(f"[ACR_IDENTIFY] Invalid timestamp '{ts}': {e}")
        return await _json_response({"status": "error", "msg": "invalid ts"})

    audio_path = _find_audio_file()
    if not audio_path:
        return await _json_response({
            "status": "error",
            "msg": "audio file not available (server may have cleaned it up)",
        })

    # Determine the gap length from the next mark; fall back to 60s for the last row.
    gap = 60.0
    try:
        import shared_utils
        sorted_keys = sorted(state.results.keys(), key=shared_utils.parse_ts)
        if ts in sorted_keys:
            idx = sorted_keys.index(ts)
            if idx + 1 < len(sorted_keys):
                gap = shared_utils.parse_ts(sorted_keys[idx + 1]) - current_sec
    except Exception as e:
        logger.warning(f"[ACR_IDENTIFY] Error computing gap for '{ts}': {e}")
    if gap <= 0:
        gap = 60.0

    try:
        from shazamio import Shazam
        from identifier import _identify_with_acrcloud
    except Exception as e:
        logger.warning(f"[ACR_IDENTIFY] Identify backend unavailable: {e}")
        return await _json_response({"status": "error", "msg": "identify backend unavailable"})

    try:
        import shared_utils
        snippets_dir = Path(state.snippets_dir) if state.snippets_dir else audio_path.parent / "snippets"
        snippets_dir.mkdir(parents=True, exist_ok=True)

        shazam_en = Shazam(language='en-US', endpoint_country='US')
        sliding_windows = shared_utils.get_optimal_sliding_windows(gap)
        logger.info(f"[ACR_IDENTIFY] {ts} (start={current_sec:.1f}s gap={gap:.1f}s windows={len(sliding_windows)})")

        found = None
        found_window = None
        raw_hits: list = []
        for i, (offset, d) in enumerate(sliding_windows):
            logger.info(
                " [ACRCloud] Window %d/%d: extract @ %.1fs (offset +%.1fs, dur %.1fs)",
                i + 1, len(sliding_windows), current_sec + offset, offset, d,
            )
            temp_name = snippets_dir / f"seg_acr_row_{int(time.time() * 1000)}_{i}.wav"
            try:
                result = await _identify_with_acrcloud(
                    shazam_en, temp_name, current_sec, offset, audio_path, sliding_windows, i,
                    collect_raw=raw_hits,
                )
                if result and result != "Unidentified":
                    found = result
                    found_window = i + 1
                    logger.info(f"[ACR_IDENTIFY] {ts} SUCCESS on window {i + 1}: {found}")
                    break
                else:
                    logger.debug(f"[ACR_IDENTIFY] {ts} no match on window {i + 1}")
            finally:
                try:
                    if temp_name.exists():
                        temp_name.unlink()
                except OSError:
                    pass

        # Best raw ACRCloud hit (first window that recognized anything), even
        # when DB resolve failed — this is what the user inspects manually.
        best_raw = raw_hits[0] if raw_hits else None
        detail_payload = None
        candidates_payload = None
        if best_raw:
            detail_payload = best_raw.get('detail')
            candidates_payload = best_raw.get('candidates')

        if found:
            display = shared_utils.format_song_entry(found)
            if state.results_file_path:
                update_results_line(Path(state.results_file_path), ts, display)
            state.results[ts] = display
            # Explicit user fix: clear any manual-review flag
            state.flagged_ts.discard(ts)
            logger.info(f"[ACR_IDENTIFY] {ts} -> {display}")
            return await _json_response({
                "status": "ok", "identified": True, "song": display,
                "window": found_window, "detail": detail_payload,
                "candidates": candidates_payload,
                "raw_windows": len(raw_hits),
            })

        logger.info(f"[ACR_IDENTIFY] {ts}: no match (raw_hits={len(raw_hits)})")
        if best_raw:
            # Recognized by ACRCloud but no DB match/discard — still return
            # the full details so the user can identify manually.
            return await _json_response({
                "status": "ok", "identified": False,
                "msg": "ACRCloud recognized audio but no database match",
                "detail": detail_payload, "candidates": candidates_payload,
                "raw_windows": len(raw_hits),
            })
        return await _json_response({"status": "ok", "identified": False, "msg": "ACRCloud found no match", "raw_windows": 0})
    except Exception as e:
        logger.warning(f"[ACR_IDENTIFY] Unexpected error for '{ts}': {e}")
        return await _json_response({"status": "error", "msg": str(e)})


async def handle_toggle_flag(request: web.Request) -> web.Response:
    """Handle /toggle_flag endpoint - flag/unflag a row for manual review.

    Appends (or strips) a trailing 🚩 marker on the row's line in results.txt.
    Query params:
        ts: Timestamp of the row (e.g. "1:30")
        flag: "1" to flag, "0" to unflag (default "1")
    """
    ts = request.query.get('ts')
    if not ts or not state.results_file_path:
        return await _json_response({"status": "error", "msg": "missing params"})

    want_flag = request.query.get('flag', '1') not in ('0', 'false', 'no', 'off')

    try:
        import shared_utils
        filepath = Path(state.results_file_path)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        lines = []
        if filepath.exists():
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()

        new_lines = []
        matched = False
        for line in lines:
            stripped = line.rstrip('\n').rstrip('\r')
            m = _TIMESTAMP_PATTERN.match(stripped)
            if m and m.group(1) == ts and not matched:
                matched = True
                canonical, _ = _split_flag_marker(m.group(2) or "")
                if want_flag:
                    new_content = f"{canonical} {FLAG_MARKER}" if canonical else FLAG_MARKER
                    state.flagged_ts.add(ts)
                else:
                    new_content = canonical
                    state.flagged_ts.discard(ts)
                # Keep in-memory results canonical so save_state() re-applies the marker itself
                state.results[ts] = canonical
                new_lines.append(f"{ts} {new_content}\n" if new_content else f"{ts}\n")
            else:
                new_lines.append(line if line.endswith('\n') else line + '\n')

        if not matched:
            if want_flag:
                new_lines.append(f"{ts} {FLAG_MARKER}\n")
                state.flagged_ts.add(ts)
                state.results.setdefault(ts, "")

                def _get_ts(l):
                    m = _TIMESTAMP_PATTERN.match(l.strip())
                    return shared_utils.parse_ts(m.group(1)) if m else 0.0
                new_lines.sort(key=_get_ts)
            else:
                state.flagged_ts.discard(ts)

        with open(filepath, "w", encoding="utf-8", newline='') as f:
            f.writelines(new_lines)

        logger.info(f"[FLAG] {ts} flagged={want_flag}")
        return await _json_response({"status": "ok", "flagged": want_flag})
    except OSError as e:
        logger.warning(f"[FLAG] File error for '{ts}': {e}")
        return await _json_response({"status": "error", "msg": str(e)})
    except Exception as e:
        logger.warning(f"[FLAG] Unexpected error for '{ts}': {e}")
        return await _json_response({"status": "error", "msg": str(e)})


async def handle_paren_exceptions(request: web.Request) -> web.Response:
    """Return the list of song names that should preserve their parentheses."""
    return web.json_response(list(SONG_NAME_PARENS_EXCEPTIONS), headers=_cors_headers())


def create_app() -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application()

    # Add CORS middleware
    @web.middleware
    async def cors_middleware(request: web.Request, handler):
        if request.method == 'OPTIONS':
            return web.Response(headers=_cors_headers())
        return await handler(request)

    app.middlewares.append(cors_middleware)

    # Register routes
    app.router.add_get('/add_mark', handle_add_mark)
    app.router.add_get('/status', handle_status)
    app.router.add_get('/results_file', handle_results_file)
    app.router.add_get('/review_done', handle_review_done)
    app.router.add_get('/close_review', handle_close_review)
    app.router.add_get('/song_lists', handle_song_lists)
    app.router.add_get('/get_song_data', handle_get_song_data)
    app.router.add_get('/update_result', handle_update_result)
    app.router.add_get('/add_song_and_update', handle_add_song_and_update)
    app.router.add_get('/review_seek', handle_review_seek)
    app.router.add_get('/select', handle_select)
    app.router.add_get('/paren_exceptions', handle_paren_exceptions)
    app.router.add_get('/acr_identify', handle_acr_identify)
    app.router.add_get('/toggle_flag', handle_toggle_flag)
    app.router.add_post('/update_song_vars', handle_update_song_vars)

    return app


def start_server():
    """Start the HTTP server (blocking)."""
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=PORT, print=None)


def run_server_thread():
    """Run the server in a daemon thread."""
    import threading
    threading.Thread(target=start_server, daemon=True).start()
