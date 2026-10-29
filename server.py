"""
HTTP server for JRPD marker system.
Handles communication between browser userscript and Python backend.

Uses aiohttp for async I/O, eliminating thread overhead and improving concurrency.
"""
import asyncio
import json
import os
import logging
import subprocess
import re
import time
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List

from aiohttp import web

from config import PORT, MISIDENTIFIED_SONGS_FILE, MISSED_SONGS_FILE, SONG_OVERRIDES_FILE, EDITOR_PATH, RUNS_DIR
from audio_utils import format_display_name, strip_extra_info
from song_db import SONG_OVERRIDES, MISSED_SONGS, MISIDENTIFIED_SONGS, save_song_overrides, load_song_overrides

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
        self.results_keys: Dict[str, str] = {}  # row ts -> registered song key (exact row ownership)
        self.is_finished = False
        self.is_session_done = False
        self.quit_requested = False
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
        self.results_keys = {}
        self.is_finished = False
        self.is_session_done = False
        self.quit_requested = False
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


def _arm_quit_watchdog(delay: float = 4.0) -> None:
    """Arm a one-shot force-quit timer in the server's own event loop.

    The main loop in label_marks_complete normally observes quit_requested /
    review_done_event and exits by itself (the console prints the [QUIT]
    lines and the process ends, like pressing Ctrl+C). If the main thread is
    stuck in a blocking phase (e.g. a long synchronous audio download before
    the loop starts), it cannot react yet — the watchdog force-terminates the
    whole process after the grace period so the console always quits.
    """
    def _force_exit():
        logger.warning("[QUIT] Graceful quit timed out; force-terminating process.")
        os._exit(0)

    try:
        asyncio.get_running_loop().call_later(delay, _force_exit)
    except RuntimeError as e:
        logger.warning(f"[QUIT] Could not arm force-quit watchdog: {e}")


async def handle_quit_session(request: web.Request) -> web.Response:
    """Handle /quit_session endpoint — abort the session, delete local audio.

    Removes the session's audio file, partial download leftovers and snippet
    temp files. Text/JSON outputs (results.txt, progress.json,
    unidentified.json) are untouched.

    Wakes the main loop so label_marks_complete.py exits: mid-identification
    via the quit_requested flag, review mode via review_done_event (kind
    "quit"), and the cleanup gap loop via a "q" selection.
    """
    _delete_session_audio()
    state.quit_requested = True
    if state.selection_queue and state.main_loop:
        state.main_loop.call_soon_threadsafe(state.selection_queue.put_nowait, "q")
    if state.main_loop and state.review_done_event:
        state.review_done_kind = "quit"
        state.main_loop.call_soon_threadsafe(state.review_done_event.set)
    # Belt-and-braces: if the graceful path above can't finish because the
    # main thread is blocked (e.g. mid-download), force-quit the process.
    _arm_quit_watchdog()
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
        if canonical:
            _note_row_key(ts, display=canonical)
        else:
            # Blanked row: drop ownership binding
            state.results_keys.pop(ts, None)
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
            _note_row_key(ts, key=new_song_key)
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


def _exact_display_to_key(display):
    """Exact reverse match: rebuild each known key's display and compare.

    Returns the owning key or None. (Keys are raw engine titles now, so a row
    display like "A (something) (EN name) - artist" can't be parsed from text;
    the display format belongs to the server.)
    """
    stores = (SONG_OVERRIDES, MISSED_SONGS, MISIDENTIFIED_SONGS)
    for store in stores:
        for key, data in store.items():
            try:
                candidate = format_display_name(
                    key,
                    data.get('intl'),
                    data.get('artist_orig'),
                    data.get('artist_intl'),
                    data.get('info')
                )
            except Exception:
                continue
            if candidate == display:
                return key
    return None


def _note_row_key(ts, key=None, display=None):
    """Record which registered song key a results row belongs to.

    The binding is persisted in progress.json (results_keys) and drives exact
    row identification for the edit modal and row rewrites. When only display
    text is available, an exact format match resolves the key; otherwise an
    existing binding is kept (raw text edits rarely change the underlying song).
    """
    if not ts:
        return
    if key:
        state.results_keys[ts] = key
        return
    if not display:
        return
    matched = _exact_display_to_key(display)
    if matched:
        state.results_keys[ts] = matched
    # No exact match: keep the existing binding (if any) untouched.


async def handle_song_key_from_display(request: web.Request) -> web.Response:
    """Handle /song_key_from_display endpoint.

    Reverse-match a results-row display string back to its registration key.

    1) Row key binding (exact): if progress.json recorded the row's key, it wins.
    2) Exact match: rebuild each known key's display and compare.
    3) Heuristic fallback: song part before " - ", then paren-stripped
       (server-side strip_extra_info, which honors the exceptions list).
    """
    ts = (request.query.get('ts') or '').strip()
    bound = state.results_keys.get(ts) if ts else None
    if bound:
        return web.json_response({"key": bound, "exact": True}, headers=_cors_headers())

    display = (request.query.get('display') or '').strip()

    if not display:
        return web.json_response({"key": bound or None, "exact": False}, headers=_cors_headers())

    key = _exact_display_to_key(display)
    if key:
        return web.json_response({"key": key, "exact": True}, headers=_cors_headers())

    # Heuristic fallback: song part before " - ", then paren-stripped
    song_part = display.split(' - ')[0].strip()
    if song_part:
        for store in (SONG_OVERRIDES, MISSED_SONGS, MISIDENTIFIED_SONGS):
            if song_part in store:
                return web.json_response({"key": song_part, "exact": False}, headers=_cors_headers())
        stripped = strip_extra_info(song_part)
        if stripped and stripped != song_part:
            for store in (SONG_OVERRIDES, MISSED_SONGS, MISIDENTIFIED_SONGS):
                if stripped in store:
                    return web.json_response({"key": stripped, "exact": False}, headers=_cors_headers())

    return web.json_response({"key": song_part or None, "exact": False}, headers=_cors_headers())


def _row_matches_song_part(song_part, key, known_keys):
    """Decide whether a results row's song text belongs to `key`.

    Match rule: `song_part` must START WITH `key` (key followed by a space,
    "(", or the exact end), AND no other longer known key may also prefix it.
    Longest-match keeps sibling raw variants separate: the row
    "A (Movie Ver.) - other" belongs to key "A (Movie Ver.)", never to "A".
    Plain substring search is unsafe with short raw keys (key "A" would match
    unrelated rows via letters inside e.g. "Artist"/"Another Song").
    """
    def _pref(k):
        return song_part == k or song_part.startswith(k + " ") or song_part.startswith(k + "(")

    if not song_part or not _pref(key):
        return False
    return not any(len(k) > len(key) and _pref(k) for k in known_keys)


async def handle_update_song_vars(request: web.Request) -> web.Response:
    """Handle /update_song_vars endpoint."""
    try:
        # Parse POST data for updating song variables
        post_data = await request.post()

        song_key = post_data.get('key')
        new_song_key = (post_data.get('new_key') or '').strip()
        renaming = bool(new_song_key and new_song_key != song_key)
        edit_ts = (post_data.get('ts') or '').strip()  # the row the user clicked (optional exact anchor)

        # DEBUG: Log incoming parameters
        logger.info(f"[UPDATE_SONG_VARS] DEBUG: Received request")
        logger.info(f"[UPDATE_SONG_VARS] DEBUG: song_key='{song_key}' new_key='{new_song_key}' renaming={renaming}")
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
        if renaming:
            # Rename semantics: the old key becomes a pure redirect
            # ({remap: new_key}); its stored fields move to the new key
            # (fill-empty-only when the target already exists).
            old_entry = SONG_OVERRIDES.get(song_key)
            if old_entry is None:
                result = {"status": "error", "msg": f"key '{song_key}' not found in songs.json"}
                return await _json_response(result)

            target_entry = SONG_OVERRIDES.setdefault(new_song_key, {})
            moved_any = False
            for field in text_fields:
                # 'remap' is never moved: it becomes the marker of the old shell
                if field != 'remap' and field in old_entry and not target_entry.get(field):
                    target_entry[field] = old_entry[field]
                    moved_any = True
            for field in bool_fields:
                if old_entry.get(field) and not target_entry.get(field):
                    target_entry[field] = old_entry[field]
                    moved_any = True

            # A target that was a pure redirect shell but just received real
            # fields becomes its own record: clear its remap.
            if moved_any and 'remap' in target_entry:
                target_entry.pop('remap')
                result["actions"].append(f"cleared_target_remap: {new_song_key}")

            # A rename must mean only that: fields move to the new key under
            # fill-empty semantics, old key keeps only the redirect. The form's
            # field values (prefilled from the OLD entry) are NOT replayed here —
            # replaying them would clobber the target's existing values. Field
            # edits are only honored in plain (non-rename) edits.
            logger.info("[UPDATE_SONG_VARS] Rename: form field edits ignored (fill-empty semantics only)")

            # Old key keeps only the redirect rule.
            old_entry.clear()
            old_entry['remap'] = new_song_key

            # Re-label row key bindings: rows owned by the old raw key now
            # belong to the canonical new key (no results.txt text changes).
            relabeled = 0
            for row_ts, bound in list(state.results_keys.items()):
                if bound == song_key:
                    state.results_keys[row_ts] = new_song_key
                    relabeled += 1
            if relabeled:
                logger.info(f"[UPDATE_SONG_VARS] Re-labeled {relabeled} row key binding(s): {song_key} -> {new_song_key}")

            save_song_overrides()
            result["actions"].append(f"renamed: {song_key} -> {new_song_key}")
            logger.info(f"[UPDATE_SONG_VARS] Renamed '{song_key}' -> '{new_song_key}' (fields moved; old key now remaps)")
        else:
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

        # Rewrite results.txt rows so rows reflect the change.
        # Plain edits: rows owned by song_key are rebuilt from its record.
        # Renames: rows owned by the OLD key are rebuilt from the NEW key's
        #   record (bindings were re-labeled just above).
        # Row ownership, most exact first:
        #   1. progress.json key binding (state.results_keys[ts])
        #   2. the row the user clicked in the review panel (ts anchor, plain
        #      edits only — a rename's anchor row is covered by its binding)
        #   3. legacy text matching for unbound rows (longest-match, see
        #      _row_matches_song_part; keeps sibling raw variants separate)
        # Rows bound to a DIFFERENT key are never rewritten.
        if state.results_file_path and Path(state.results_file_path).exists():
            record_key = new_song_key if renaming else song_key
            song_data = SONG_OVERRIDES.get(record_key, {})
            new_display = format_display_name(
                record_key,
                song_data.get('intl'),
                song_data.get('artist_orig'),
                song_data.get('artist_intl'),
                song_data.get('info')
            )
            known_keys = list(SONG_OVERRIDES.keys())

            # Read and update results.txt
            with open(state.results_file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            new_lines = []
            updated_count = 0
            for line in lines:
                stripped = line.rstrip('\n').rstrip('\r')
                m = _TIMESTAMP_PATTERN.match(stripped)
                line_ts = m.group(1) if m else None
                song_part, _ = _split_flag_marker((m.group(2) or "") if m else stripped)
                song_part = song_part.strip()
                bound_key = state.results_keys.get(line_ts) if line_ts else None
                if renaming:
                    # Bindings were re-labeled old -> new, so post-relabel
                    # bindings pointing at the new key are owned rows. Unbound
                    # legacy rows keep the old raw text: match by old name.
                    matched = bound_key == record_key or (
                        bound_key is None and _row_matches_song_part(song_part, song_key, known_keys)
                    )
                else:
                    if bound_key == song_key:
                        matched = True
                    elif line_ts and edit_ts and line_ts == edit_ts:
                        matched = True
                    elif bound_key is None:
                        matched = _row_matches_song_part(song_part, song_key, known_keys)
                    else:
                        matched = False
                if matched:
                    if m:
                        ts = line_ts
                        # Preserve any manual-review flag on this row
                        _, was_flagged = _split_flag_marker(m.group(2) or "")
                        new_lines.append(f"{ts} {new_display} {FLAG_MARKER}\n" if was_flagged else f"{ts} {new_display}\n")
                        if was_flagged:
                            state.flagged_ts.add(ts)
                        updated_count += 1
                        # Bind ownership + mirror into in-memory results so
                        # save_state() preserves both
                        state.results_keys[ts] = record_key
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

# Audio artifacts removable by /quit_session: the audio file itself (matched
# by "audio.*", which also covers audio.m4s and audio.*.progress.json download
# checkpoints) plus partial download leftovers. None of these patterns can
# match the user outputs results.txt / progress.json / unidentified.json; the
# protected-names check below is belt-and-braces. .yt_dlp_cache is skipped,
# same as _remove_partial_downloads() in audio_utils.
_AUDIO_ARTIFACT_PATTERNS = ("audio.*", "*.aria2", "*.part", "*.ytdl", "*.temp")
_QUIT_PROTECTED_FILES = {"results.txt", "progress.json", "unidentified.json"}


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


def _delete_session_audio() -> int:
    """Delete the current session's local audio artifacts (files only).

    Fired by /quit_session when the review panel Quit button is clicked.
    Removes the downloaded audio, partial download leftovers and temp
    identification snippets. User outputs (results.txt, progress.json,
    unidentified.json), the song DB json files and .yt_dlp_cache are never
    touched. Returns the number of files deleted.
    """
    deleted = 0

    # The audio file the identification pipeline recorded, when known.
    if state.audio_path:
        p = Path(state.audio_path)
        try:
            if p.exists():
                p.unlink()
                deleted += 1
        except OSError as e:
            logger.warning(f"[QUIT] Could not delete {p.name}: {e}")

    session_dir = None
    if state.results_file_path:
        session_dir = Path(state.results_file_path).parent
    elif state.snippets_dir:
        session_dir = Path(state.snippets_dir).parent

    if not session_dir or not session_dir.exists():
        logger.info(f"[QUIT] No session directory for audio cleanup (deleted={deleted}).")
        return deleted

    try:
        for pat in _AUDIO_ARTIFACT_PATTERNS:
            for stale in session_dir.glob(pat):
                if not stale.is_file() or stale.name == ".yt_dlp_cache":
                    continue
                if stale.name.lower() in _QUIT_PROTECTED_FILES:
                    continue
                try:
                    stale.unlink()
                    deleted += 1
                except OSError as e:
                    logger.warning(f"[QUIT] Could not delete {stale.name}: {e}")

        # Temporary identification snippets (seg_*.wav etc.); files only.
        snippets_dir = Path(state.snippets_dir) if state.snippets_dir else session_dir / "snippets"
        if snippets_dir.exists():
            for seg in snippets_dir.iterdir():
                if not seg.is_file():
                    continue
                try:
                    seg.unlink()
                    deleted += 1
                except OSError as e:
                    logger.warning(f"[QUIT] Could not delete {seg.name}: {e}")
    except Exception as e:
        logger.warning(f"[QUIT] Audio artifact cleanup failed: {e}")

    if deleted:
        logger.info(f"[QUIT] Deleted {deleted} local audio artifact file(s).")
    return deleted


async def handle_acr_identify(request: web.Request) -> web.Response:
    """Handle /acr_identify endpoint - re-identify a single row with AHA Music.

    Falls back to ACRCloud when AHA Music finds no database match.

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
        from identifier import _identify_with_acrcloud, _identify_with_aha
        from aha_api import AhaRateLimitedError
        import acrcloud
        from acrcloud import AcrQuotaExceededError
        from config import AHA_CONFIG
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
        found_source = None
        aha_hits: list = []
        aha_rate_limited = False
        if AHA_CONFIG.get('enabled', True):
            for i, (offset, d) in enumerate(sliding_windows):
                logger.info(
                    " [AHA] Window %d/%d: extract @ %.1fs (offset +%.1fs, dur %.1fs)",
                    i + 1, len(sliding_windows), current_sec + offset, offset, d,
                )
                temp_name = snippets_dir / f"seg_aha_row_{int(time.time() * 1000)}_{i}.wav"
                try:
                    result = await _identify_with_aha(
                        shazam_en, temp_name, current_sec, offset, audio_path, sliding_windows, i,
                        collect_raw=aha_hits,
                    )
                    if result and result != "Unidentified":
                        found = result
                        found_window = i + 1
                        found_source = "aha"
                        logger.info(f"[ACR_IDENTIFY] {ts} AHA SUCCESS on window {i + 1}: {found}")
                        break
                    else:
                        logger.debug(f"[ACR_IDENTIFY] {ts} AHA no match on window {i + 1}")
                except AhaRateLimitedError as e:
                    # 429 through the whole retry ladder: stop firing AHA
                    # for the remaining windows of this pass and fall
                    # through to the ACRCloud fallback.
                    aha_rate_limited = True
                    logger.warning(
                        f"[ACR_IDENTIFY] {ts} AHA rate-limited (HTTP 429 x{e.attempts}) — skipping remaining AHA windows, trying ACRCloud"
                    )
                    break
                finally:
                    try:
                        if temp_name.exists():
                            temp_name.unlink()
                    except OSError:
                        pass
        else:
            logger.debug(f"[ACR_IDENTIFY] {ts} AHA disabled via config, skipping")

        # ACRCloud fallback.
        raw_hits: list = []
        acr_quota_exhausted = acrcloud.quota_exhausted()
        if not found and not acr_quota_exhausted:
            logger.info(f"[ACR_IDENTIFY] {ts} AHA found no DB match, trying ACRCloud")
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
                        found_source = "acrcloud"
                        logger.info(f"[ACR_IDENTIFY] {ts} SUCCESS on window {i + 1}: {found}")
                        break
                    else:
                        logger.debug(f"[ACR_IDENTIFY] {ts} no match on window {i + 1}")
                except AcrQuotaExceededError as e:
                    # Account limit confirmed live: the module flag now
                    # blocks every later ACR call in this process; stop
                    # firing the remaining windows of this pass too.
                    acr_quota_exhausted = True
                    acrcloud._quota_exhausted = True
                    logger.warning(
                        f"[ACR_IDENTIFY] {ts} ACRCloud quota exceeded (code {e.code}) — skipping remaining ACR windows"
                    )
                    break
                finally:
                    try:
                        if temp_name.exists():
                            temp_name.unlink()
                    except OSError:
                        pass
        elif acr_quota_exhausted:
            logger.warning(f"[ACR_IDENTIFY] {ts} ACRCloud quota already exhausted (3003) this run — skipping ACR fallback")

        # Best raw hit (first window that recognized anything), even
        # when DB resolve failed — this is what the user inspects manually.
        best_raw = aha_hits[0] if aha_hits else (raw_hits[0] if raw_hits else None)
        raw_source = "aha" if aha_hits else ("acrcloud" if raw_hits else None)
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
            _note_row_key(ts, display=display)
            # Explicit user fix: clear any manual-review flag
            state.flagged_ts.discard(ts)
            logger.info(f"[ACR_IDENTIFY] {ts} -> {display} (via {found_source})")
            return await _json_response({
                "status": "ok", "identified": True, "song": display,
                "window": found_window, "source": found_source,
                "detail": detail_payload,
                "candidates": candidates_payload,
                "raw_windows": len(raw_hits) + len(aha_hits),
                "aha_rate_limited": aha_rate_limited,
                "acr_quota_exceeded": acr_quota_exhausted,
            })

        logger.info(f"[ACR_IDENTIFY] {ts}: no match (raw_hits={len(raw_hits)} aha_hits={len(aha_hits)})")
        if best_raw:
            # Recognized but no DB match/discard — still return
            # the full details so the user can identify manually.
            return await _json_response({
                "status": "ok", "identified": False,
                "msg": "ACRCloud recognized audio but no database match",
                "source": raw_source,
                "detail": detail_payload, "candidates": candidates_payload,
                "raw_windows": len(raw_hits) + len(aha_hits),
                "aha_rate_limited": aha_rate_limited,
                "acr_quota_exceeded": acr_quota_exhausted,
            })
        if acr_quota_exhausted and not aha_hits:
            msg = "ACRCloud quota exceeded (requests limit reached — upgrade or wait for the plan reset)"
        elif acr_quota_exhausted:
            msg = "AHA found no match; ACRCloud quota exceeded (requests limit reached)"
        elif aha_rate_limited:
            msg = "AHA rate-limited; ACRCloud found no match"
        else:
            msg = "ACRCloud found no match"
        return await _json_response({"status": "ok", "identified": False, "msg": msg, "raw_windows": 0, "aha_rate_limited": aha_rate_limited, "acr_quota_exceeded": acr_quota_exhausted})
    except Exception as e:
        logger.warning(f"[ACR_IDENTIFY] Unexpected error for '{ts}': {e}")
        return await _json_response({"status": "error", "msg": str(e)})


def _summarize_identify_source(raw_hits: list, song=None, window=None, disabled=False, blocked=None) -> Dict[str, Any]:
    """Build one engine's side-by-side payload for /identify_all.

    Args:
        raw_hits: raw recognize dicts collected across windows (first = best).
        song: resolved DB display string, or None when no DB match.
        window: 1-based window index where the DB match was found.
        disabled: True when the engine was skipped via config.
        blocked: None, or a reason string when live probing was cut short
            (e.g. "rate_limited" after the endpoint 429-ed every attempt).
    """
    best = raw_hits[0] if raw_hits else None
    detail = best.get('detail') if isinstance(best, dict) else None
    candidates = best.get('candidates') if isinstance(best, dict) else None
    raw_title = best.get('title') if isinstance(best, dict) else None
    raw_artist = best.get('artist') if isinstance(best, dict) else None
    # Shazam detail carries title/artist too; fall back to it when present.
    if (not raw_title or not raw_artist) and isinstance(detail, dict):
        raw_title = raw_title or detail.get('title')
        raw_artist = raw_artist or detail.get('artist')
    return {
        "song": song,
        "window": window,
        "detail": detail,
        "candidates": candidates,
        "raw_title": raw_title,
        "raw_artist": raw_artist,
        "raw_windows": len(raw_hits),
        "disabled": disabled,
        "blocked": blocked,
    }


# In-flight /identify_all jobs for progress polling: job_id -> dict with
# ts / done / window (windows finished) / total / found (engine -> bool) /
# results / error / cancelled / task. Finished jobs are pruned lazily.
_identify_jobs: Dict[str, Dict[str, Any]] = {}
_IDENTIFY_JOB_TTL = 600.0  # seconds


def _prune_identify_jobs(now: Optional[float] = None) -> None:
    """Drop finished identify jobs older than _IDENTIFY_JOB_TTL."""
    now = now if now is not None else time.time()
    stale = [
        jid for jid, j in _identify_jobs.items()
        if j.get("done") and now - j.get("finished_at", now) > _IDENTIFY_JOB_TTL
    ]
    for jid in stale:
        _identify_jobs.pop(jid, None)


def _prepare_identify_all(ts: str):
    """Validate ts/audio and compute the gap for the /identify_all* endpoints.

    Returns:
        Tuple (prep, error) where prep is
        {"current_sec", "gap", "audio_path"} or None when error is set.
    """
    try:
        import shared_utils
        current_sec = shared_utils.parse_ts(ts)
    except Exception as e:
        logger.warning(f"[IDENTIFY_ALL] Invalid timestamp '{ts}': {e}")
        return None, "invalid ts"

    audio_path = _find_audio_file()
    if not audio_path:
        return None, "audio file not available (server may have cleaned it up)"

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
        logger.warning(f"[IDENTIFY_ALL] Error computing gap for '{ts}': {e}")
    if gap <= 0:
        gap = 60.0
    return {"current_sec": current_sec, "gap": gap, "audio_path": audio_path}, None


async def _run_identify_all_job(job_id: str, ts: str, prep: Dict[str, Any]) -> None:
    """Background worker for /identify_all_start: fills the job dict."""
    job = _identify_jobs.get(job_id)
    if not job:
        return
    try:
        from shazamio import Shazam
        from identifier import (
            _extract_audio_segment,
            _recognize_shazam_snippet,
            _recognize_aha_snippet,
            _recognize_acrcloud_snippet,
        )
        from aha_api import AhaRateLimitedError
        import acrcloud
        from acrcloud import AcrQuotaExceededError
        from config import AHA_CONFIG
    except Exception as e:
        logger.warning(f"[IDENTIFY_ALL] Identify backend unavailable: {e}")
        job["done"] = True
        job["error"] = "identify backend unavailable"
        job["finished_at"] = time.time()
        return

    try:
        import shared_utils
        current_sec = prep["current_sec"]
        gap = prep["gap"]
        audio_path = prep["audio_path"]
        snippets_dir = Path(state.snippets_dir) if state.snippets_dir else audio_path.parent / "snippets"
        snippets_dir.mkdir(parents=True, exist_ok=True)

        shazam = Shazam(language='ja-JP', endpoint_country='JP')
        shazam_en = Shazam(language='en-US', endpoint_country='US')
        sliding_windows = shared_utils.get_optimal_sliding_windows(gap)
        job["total"] = len(sliding_windows)
        logger.info(f"[IDENTIFY_ALL] {ts} (start={current_sec:.1f}s gap={gap:.1f}s windows={len(sliding_windows)})")

        aha_enabled = AHA_CONFIG.get('enabled', True)
        if not aha_enabled:
            logger.debug(f"[IDENTIFY_ALL] {ts} AHA disabled via config, skipping")
        aha_rate_limited = False  # set once the endpoint 429s through the retry ladder
        # ACR in-process quota stop-flag: true once code 3003 was confirmed
        # anywhere in this process (auto path, /acr_identify, or this sweep).
        acr_quota_exhausted = acrcloud.quota_exhausted()

        shazam_raw: list = []
        aha_raw: list = []
        acr_raw: list = []
        found = {"shazam": None, "aha": None, "acrcloud": None}
        found_window = {"shazam": None, "aha": None, "acrcloud": None}

        for i, (offset, d) in enumerate(sliding_windows):
            if found["shazam"] and (found["aha"] or not aha_enabled or aha_rate_limited) and (found["acrcloud"] or acr_quota_exhausted):
                break
            logger.info(
                " [IDENTIFY_ALL] Window %d/%d: extract @ %.1fs (offset +%.1fs, dur %.1fs)",
                i + 1, len(sliding_windows), current_sec + offset, offset, d,
            )
            temp_name = snippets_dir / f"seg_all_row_{int(time.time() * 1000)}_{i}.wav"
            # Live per-engine status for the progress modal. "Matched"
            # engines keep their matched state across later windows.
            job["window"] = i + 1
            job["scan_sec"] = current_sec + offset
            job["stage"] = "extracting"
            prev_engines = job.get("engines", {})
            def _carried(label):
                """Keep a matched engine's full status (incl. its window #)."""
                if not found[label]:
                    return {"status": "waiting"}
                prev = prev_engines.get(label) or {}
                return {"status": "matched", "window": prev.get("window")}
            def _aha_slot():
                if not aha_enabled:
                    return {"status": "disabled"}
                if aha_rate_limited:
                    return {"status": "rate_limited"}
                return _carried("aha")
            def _acr_slot():
                if acr_quota_exhausted:
                    return {"status": "quota_exceeded"}
                return _carried("acrcloud")
            job["engines"] = {
                "shazam": _carried("shazam"),
                "aha": _aha_slot(),
                "acrcloud": _acr_slot(),
            }
            try:
                ok = await _extract_audio_segment(
                    audio_path, current_sec, offset, d, temp_name
                )
                if not ok:
                    logger.debug(f"[IDENTIFY_ALL] {ts} window {i + 1}: extraction failed, skipping")
                    continue

                job["stage"] = "querying"
                tasks = {}
                if not found["shazam"]:
                    fut = asyncio.ensure_future(_recognize_shazam_snippet(shazam, shazam_en, temp_name, collect_raw=shazam_raw))
                    tasks[fut] = "shazam"
                    job["engines"]["shazam"] = {"status": "running"}
                if aha_enabled and not found["aha"] and not aha_rate_limited:
                    fut = asyncio.ensure_future(_recognize_aha_snippet(shazam_en, temp_name, collect_raw=aha_raw))
                    tasks[fut] = "aha"
                    job["engines"]["aha"] = {"status": "running"}
                if not found["acrcloud"] and not acr_quota_exhausted:
                    fut = asyncio.ensure_future(_recognize_acrcloud_snippet(shazam_en, temp_name, collect_raw=acr_raw))
                    tasks[fut] = "acrcloud"
                    job["engines"]["acrcloud"] = {"status": "running"}
                if not tasks:
                    break

                # Resolve engines one-by-one so the progress modal updates
                # as each request finishes, not only after the whole window.
                pending = set(tasks.keys())
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for fut in done:
                        label = tasks[fut]
                        try:
                            outcome = fut.result()
                        except AhaRateLimitedError as e:
                            # Server is 429-ing everything now. Stop firing
                            # AHA for the remaining windows of THIS sweep;
                            # the next sweep (next mark / re-identify click)
                            # retries normally with the backoff ladder.
                            aha_rate_limited = True
                            job["engines"][label] = {"status": "rate_limited"}
                            logger.warning(
                                f"[IDENTIFY_ALL] {ts} AHA rate-limited (HTTP 429 x{e.attempts}) — skipping remaining AHA windows this sweep"
                            )
                            continue
                        except AcrQuotaExceededError as e:
                            # Account limit confirmed: stop firing ACR for
                            # the remaining windows of THIS sweep; the
                            # module flag now blocks every later call in
                            # this process (next sweeps skip without
                            # spending a single request).
                            acr_quota_exhausted = True
                            acrcloud._quota_exhausted = True
                            job["engines"][label] = {"status": "quota_exceeded"}
                            logger.warning(
                                f"[IDENTIFY_ALL] {ts} ACRCloud quota exceeded (code {e.code}) — skipping remaining ACR windows this sweep"
                            )
                            continue
                        except Exception as e:
                            logger.warning(f"[IDENTIFY_ALL] {ts} {label} window {i + 1} error: {e}")
                            job["engines"][label] = {"status": "error"}
                            continue
                        if outcome and outcome != "Unidentified":
                            found[label] = outcome
                            found_window[label] = i + 1
                            job["engines"][label] = {"status": "matched", "window": i + 1}
                            logger.info(f"[IDENTIFY_ALL] {ts} {label.upper()} SUCCESS on window {i + 1}: {outcome}")
                        else:
                            job["engines"][label] = {"status": "no-match"}
                            logger.debug(f"[IDENTIFY_ALL] {ts} {label} no DB match on window {i + 1}")
                        job["found"] = {k: bool(v) for k, v in found.items()}
            finally:
                try:
                    if temp_name.exists():
                        temp_name.unlink()
                except OSError:
                    pass
            job["windows_done"] = i + 1

        job["results"] = {
            "shazam": _summarize_identify_source(shazam_raw, found["shazam"], found_window["shazam"]),
            "aha": _summarize_identify_source(aha_raw, found["aha"], found_window["aha"], disabled=not aha_enabled, blocked="rate_limited" if aha_rate_limited else None),
            "acrcloud": _summarize_identify_source(acr_raw, found["acrcloud"], found_window["acrcloud"], blocked="quota_exceeded" if acr_quota_exhausted else None),
        }
        logger.info(
            f"[IDENTIFY_ALL] {ts} done: shazam={found['shazam']!r} aha={found['aha']!r} acrcloud={found['acrcloud']!r}"
            + (f" (aha rate-limited)" if aha_rate_limited else "")
            + (f" (acr quota-exceeded)" if acr_quota_exhausted else "")
        )
    except asyncio.CancelledError:
        logger.info(f"[IDENTIFY_ALL] {ts} job {job_id} cancelled")
        job["done"] = True
        job["cancelled"] = True
        raise
    except Exception as e:
        logger.warning(f"[IDENTIFY_ALL] Unexpected error for '{ts}': {e}")
        job["error"] = str(e)
    finally:
        job["done"] = True
        job["finished_at"] = time.time()


async def handle_identify_all_start(request: web.Request) -> web.Response:
    """Handle /identify_all_start - launch a background 3-engine identify job.

    Returns immediately with a job id plus the window count so the
    frontend can render progress. Poll /identify_all_job for status.

    Query params:
        ts: Timestamp of the row to identify (e.g. "1:30")
    """
    ts = request.query.get('ts')
    if not ts:
        return await _json_response({"status": "error", "msg": "missing ts"})

    prep, error = _prepare_identify_all(ts)
    if error:
        return await _json_response({"status": "error", "msg": error})

    try:
        import shared_utils
        total = len(shared_utils.get_optimal_sliding_windows(prep["gap"]))
    except Exception as e:
        logger.warning(f"[IDENTIFY_ALL] Error computing windows for '{ts}': {e}")
        return await _json_response({"status": "error", "msg": "cannot compute windows"})

    try:
        from config import AHA_CONFIG
        aha_enabled = AHA_CONFIG.get('enabled', True)
    except Exception:
        aha_enabled = True

    _prune_identify_jobs()
    job_id = uuid.uuid4().hex[:12]
    _identify_jobs[job_id] = {
        "ts": ts, "done": False, "window": 0, "total": total,
        "windows_done": 0, "stage": "starting", "scan_sec": None,
        "engines": {"shazam": {"status": "waiting"}, "aha": {"status": "waiting"}, "acrcloud": {"status": "waiting"}},
        "aha_enabled": aha_enabled,
        "found": {"shazam": False, "aha": False, "acrcloud": False},
        "results": None, "error": None, "cancelled": False,
        "started_at": time.time(),
    }
    task = asyncio.create_task(_run_identify_all_job(job_id, ts, prep))
    _identify_jobs[job_id]["task"] = task
    logger.info(f"[IDENTIFY_ALL] {ts} job {job_id} started ({total} windows)")
    return await _json_response({"status": "ok", "job": job_id, "ts": ts, "total": total, "aha_enabled": aha_enabled})


async def handle_identify_all_job(request: web.Request) -> web.Response:
    """Handle /identify_all_job - poll a background identify job.

    Query params:
        job: Job id returned by /identify_all_start
    """
    job_id = request.query.get('job')
    job = _identify_jobs.get(job_id) if job_id else None
    if not job:
        return await _json_response({"status": "error", "msg": "unknown job"})
    payload: Dict[str, Any] = {
        "status": "ok", "done": job["done"], "ts": job["ts"],
        "window": job["window"], "total": job["total"], "found": job["found"],
        "windows_done": job.get("windows_done", 0),
        "stage": job.get("stage", ""),
        "scan_sec": job.get("scan_sec"),
        "engines": job.get("engines", {}),
        "aha_enabled": job.get("aha_enabled", True),
    }
    if job.get("error"):
        payload["job_error"] = job["error"]
    if job.get("cancelled"):
        payload["cancelled"] = True
    if job["done"] and job.get("results") is not None:
        payload["results"] = job["results"]
    return await _json_response(payload)


async def handle_identify_all_cancel(request: web.Request) -> web.Response:
    """Handle /identify_all_cancel - cancel a background identify job.

    Query params:
        job: Job id returned by /identify_all_start
    """
    job_id = request.query.get('job')
    job = _identify_jobs.get(job_id) if job_id else None
    if not job:
        return await _json_response({"status": "ok", "msg": "unknown job"})
    task = job.get("task")
    try:
        if task and not task.done():
            task.cancel()
    except Exception as e:
        logger.warning(f"[IDENTIFY_ALL] Error cancelling job {job_id}: {e}")
    job["cancelled"] = True
    return await _json_response({"status": "ok"})


async def handle_identify_all(request: web.Request) -> web.Response:
    """Handle /identify_all endpoint - re-identify one row with all 3 engines.

    Runs Shazam (shazamio), AHA Music and ACRCloud over the same
    sliding windows (one audio extraction per window, engines queried
    concurrently) and returns each engine's best result side-by-side so
    the user can pick which one to apply to the row. Nothing is written
    to results.txt here — the frontend applies the chosen song via the
    existing /update_result endpoint.

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
        logger.warning(f"[IDENTIFY_ALL] Invalid timestamp '{ts}': {e}")
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
        logger.warning(f"[IDENTIFY_ALL] Error computing gap for '{ts}': {e}")
    if gap <= 0:
        gap = 60.0

    try:
        from shazamio import Shazam
        from identifier import (
            _extract_audio_segment,
            _recognize_shazam_snippet,
            _recognize_aha_snippet,
            _recognize_acrcloud_snippet,
        )
        from aha_api import AhaRateLimitedError
        import acrcloud
        from acrcloud import AcrQuotaExceededError
        from config import AHA_CONFIG
    except Exception as e:
        logger.warning(f"[IDENTIFY_ALL] Identify backend unavailable: {e}")
        return await _json_response({"status": "error", "msg": "identify backend unavailable"})

    try:
        import shared_utils
        snippets_dir = Path(state.snippets_dir) if state.snippets_dir else audio_path.parent / "snippets"
        snippets_dir.mkdir(parents=True, exist_ok=True)

        shazam = Shazam(language='ja-JP', endpoint_country='JP')
        shazam_en = Shazam(language='en-US', endpoint_country='US')
        sliding_windows = shared_utils.get_optimal_sliding_windows(gap)
        logger.info(f"[IDENTIFY_ALL] {ts} (start={current_sec:.1f}s gap={gap:.1f}s windows={len(sliding_windows)})")

        aha_enabled = AHA_CONFIG.get('enabled', True)
        if not aha_enabled:
            logger.debug(f"[IDENTIFY_ALL] {ts} AHA disabled via config, skipping")
        aha_rate_limited = False  # set once the endpoint 429s through the retry ladder
        # ACR in-process quota stop-flag: true once code 3003 was confirmed
        # anywhere in this process (auto path, /acr_identify, or this sweep).
        acr_quota_exhausted = acrcloud.quota_exhausted()

        shazam_raw: list = []
        aha_raw: list = []
        acr_raw: list = []
        found = {"shazam": None, "aha": None, "acrcloud": None}
        found_window = {"shazam": None, "aha": None, "acrcloud": None}

        for i, (offset, d) in enumerate(sliding_windows):
            if found["shazam"] and (found["aha"] or not aha_enabled or aha_rate_limited) and (found["acrcloud"] or acr_quota_exhausted):
                break
            logger.info(
                " [IDENTIFY_ALL] Window %d/%d: extract @ %.1fs (offset +%.1fs, dur %.1fs)",
                i + 1, len(sliding_windows), current_sec + offset, offset, d,
            )
            temp_name = snippets_dir / f"seg_all_row_{int(time.time() * 1000)}_{i}.wav"
            try:
                ok = await _extract_audio_segment(
                    audio_path, current_sec, offset, d, temp_name
                )
                if not ok:
                    logger.debug(f"[IDENTIFY_ALL] {ts} window {i + 1}: extraction failed, skipping")
                    continue

                jobs = []
                labels = []
                if not found["shazam"]:
                    jobs.append(_recognize_shazam_snippet(shazam, shazam_en, temp_name, collect_raw=shazam_raw))
                    labels.append("shazam")
                if aha_enabled and not found["aha"] and not aha_rate_limited:
                    jobs.append(_recognize_aha_snippet(shazam_en, temp_name, collect_raw=aha_raw))
                    labels.append("aha")
                if not found["acrcloud"] and not acr_quota_exhausted:
                    jobs.append(_recognize_acrcloud_snippet(shazam_en, temp_name, collect_raw=acr_raw))
                    labels.append("acrcloud")
                if not jobs:
                    break

                outcomes = await asyncio.gather(*jobs, return_exceptions=True)
                for label, outcome in zip(labels, outcomes):
                    if isinstance(outcome, AhaRateLimitedError):
                        # Endpoint 429-ed through the retry ladder: stop
                        # firing AHA for the rest of this sweep.
                        aha_rate_limited = True
                        logger.warning(
                            f"[IDENTIFY_ALL] {ts} AHA rate-limited (HTTP 429 x{outcome.attempts}) — skipping remaining AHA windows this sweep"
                        )
                        continue
                    if isinstance(outcome, AcrQuotaExceededError):
                        # Account limit confirmed: stop firing ACR for the
                        # rest of this sweep; the module flag blocks every
                        # later call in this process.
                        acr_quota_exhausted = True
                        acrcloud._quota_exhausted = True
                        logger.warning(
                            f"[IDENTIFY_ALL] {ts} ACRCloud quota exceeded (code {outcome.code}) — skipping remaining ACR windows this sweep"
                        )
                        continue
                    if isinstance(outcome, Exception):
                        logger.warning(f"[IDENTIFY_ALL] {ts} {label} window {i + 1} error: {outcome}")
                        continue
                    if outcome and outcome != "Unidentified":
                        found[label] = outcome
                        found_window[label] = i + 1
                        logger.info(f"[IDENTIFY_ALL] {ts} {label.upper()} SUCCESS on window {i + 1}: {outcome}")
                    else:
                        logger.debug(f"[IDENTIFY_ALL] {ts} {label} no DB match on window {i + 1}")
            finally:
                try:
                    if temp_name.exists():
                        temp_name.unlink()
                except OSError:
                    pass

        results = {
            "shazam": _summarize_identify_source(shazam_raw, found["shazam"], found_window["shazam"]),
            "aha": _summarize_identify_source(aha_raw, found["aha"], found_window["aha"], disabled=not aha_enabled, blocked="rate_limited" if aha_rate_limited else None),
            "acrcloud": _summarize_identify_source(acr_raw, found["acrcloud"], found_window["acrcloud"], blocked="quota_exceeded" if acr_quota_exhausted else None),
        }
        logger.info(
            f"[IDENTIFY_ALL] {ts} done: shazam={found['shazam']!r} aha={found['aha']!r} acrcloud={found['acrcloud']!r}"
            + (f" (aha rate-limited)" if aha_rate_limited else "")
            + (f" (acr quota-exceeded)" if acr_quota_exhausted else "")
        )
        return await _json_response({"status": "ok", "ts": ts, "results": results})
    except Exception as e:
        logger.warning(f"[IDENTIFY_ALL] Unexpected error for '{ts}': {e}")
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
    app.router.add_get('/quit_session', handle_quit_session)
    app.router.add_get('/song_lists', handle_song_lists)
    app.router.add_get('/get_song_data', handle_get_song_data)
    app.router.add_get('/update_result', handle_update_result)
    app.router.add_get('/add_song_and_update', handle_add_song_and_update)
    app.router.add_get('/review_seek', handle_review_seek)
    app.router.add_get('/select', handle_select)
    app.router.add_get('/song_key_from_display', handle_song_key_from_display)
    app.router.add_get('/acr_identify', handle_acr_identify)
    app.router.add_get('/aha_identify', handle_acr_identify)  # alias: same ACRCloud -> AHA flow
    app.router.add_get('/identify_all', handle_identify_all)
    app.router.add_get('/identify_all_start', handle_identify_all_start)
    app.router.add_get('/identify_all_job', handle_identify_all_job)
    app.router.add_get('/identify_all_cancel', handle_identify_all_cancel)
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
