"""
Song database management for JRPD marker system.
Handles loading/saving of songs.json, wrong_matches.json, missed_songs.json, misidentified_songs.json
"""
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict

from config import (
    SONG_OVERRIDES_FILE, WRONG_MATCHES_FILE, MISSED_SONGS_FILE,
    MISIDENTIFIED_SONGS_FILE, SONG_NAME_PARENS_EXCEPTIONS_FILE, DISPLAY_FORMAT
)
from audio_utils import format_display_name

logger = logging.getLogger("JRPD")

# Thread lock for in-process synchronization
_file_lock = threading.Lock()


def _atomic_write_json(filepath: Path, data: Dict[str, Any]) -> None:
    """
    Atomically write JSON data to file.

    Uses temp file + rename pattern for atomicity.
    Thread lock is only held during the atomic rename to minimize contention.

    Args:
        filepath: Target file path
        data: Dictionary to write
    """
    # Write to temp file OUTSIDE the lock to minimize lock contention
    temp_fd, temp_path = tempfile.mkstemp(
        dir=filepath.parent,
        prefix=f".{filepath.name}.",
        suffix='.tmp'
    )
    try:
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Only lock during the atomic rename operation
        with _file_lock:
            os.replace(temp_path, filepath)
    except Exception:
        # Clean up temp file on error
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


# In-memory databases
SONG_OVERRIDES = {}
WRONG_MATCHES = {}
MISSED_SONGS = {}
MISIDENTIFIED_SONGS = {}
SONG_NAME_PARENS_EXCEPTIONS = set()

# Reverse lookup index: intl_name -> orig_key (for O(1) lookups by international name)
_INTL_INDEX = {}


def _rebuild_intl_index():
    """Rebuild the international name reverse lookup index from SONG_OVERRIDES."""
    global _INTL_INDEX
    _INTL_INDEX.clear()
    for orig_name, data in SONG_OVERRIDES.items():
        intl = data.get('intl', '')
        if intl:
            _INTL_INDEX[intl] = orig_name


def load_song_overrides():
    """Load song name overrides from JSON file."""
    global SONG_OVERRIDES
    if SONG_OVERRIDES_FILE.exists():
        with open(SONG_OVERRIDES_FILE, "r", encoding="utf-8") as f:
            # Clear existing dict and update in place to preserve the reference
            SONG_OVERRIDES.clear()
            SONG_OVERRIDES.update(json.load(f))
        _rebuild_intl_index()
        logger.info(f"[OVERRIDES] Loaded {len(SONG_OVERRIDES)} entries from {SONG_OVERRIDES_FILE.name}")


def save_song_overrides():
    """Save song name overrides to JSON file (sorted alphabetically by key)."""
    sorted_overrides = dict(sorted(SONG_OVERRIDES.items(), key=lambda x: x[0].lower()))
    _atomic_write_json(SONG_OVERRIDES_FILE, sorted_overrides)
    _rebuild_intl_index()


def load_wrong_matches():
    """Load wrong matches (random garbage detections to discard) from JSON file."""
    global WRONG_MATCHES
    if WRONG_MATCHES_FILE.exists():
        with open(WRONG_MATCHES_FILE, "r", encoding="utf-8") as f:
            WRONG_MATCHES = json.load(f)
        logger.info(f"[WRONG_MATCHES] Loaded {len(WRONG_MATCHES)} entries from {WRONG_MATCHES_FILE.name}")


def load_missed_songs():
    """Load missed songs from JSON file."""
    global MISSED_SONGS
    if MISSED_SONGS_FILE.exists():
        with open(MISSED_SONGS_FILE, "r", encoding="utf-8") as f:
            MISSED_SONGS = json.load(f)
        logger.info(f"[MISSED] Loaded {len(MISSED_SONGS)} entries from {MISSED_SONGS_FILE.name}")


def save_missed_songs():
    """Save missed songs to JSON file (sorted alphabetically by key)."""
    global MISSED_SONGS
    MISSED_SONGS = dict(sorted(MISSED_SONGS.items(), key=lambda x: x[0].lower()))
    _atomic_write_json(MISSED_SONGS_FILE, MISSED_SONGS)


def load_misidentified_songs():
    """Load misidentified songs from JSON file."""
    global MISIDENTIFIED_SONGS
    if MISIDENTIFIED_SONGS_FILE.exists():
        with open(MISIDENTIFIED_SONGS_FILE, "r", encoding="utf-8") as f:
            MISIDENTIFIED_SONGS = json.load(f)
        logger.info(f"[MISIDENTIFIED] Loaded {len(MISIDENTIFIED_SONGS)} entries from {MISIDENTIFIED_SONGS_FILE.name}")


def save_misidentified_songs():
    """Save misidentified songs to JSON file (sorted alphabetically by key)."""
    global MISIDENTIFIED_SONGS
    MISIDENTIFIED_SONGS = dict(sorted(MISIDENTIFIED_SONGS.items(), key=lambda x: x[0].lower()))
    _atomic_write_json(MISIDENTIFIED_SONGS_FILE, MISIDENTIFIED_SONGS)


def load_song_name_parentheses_exceptions():
    """Load song name parentheses exceptions from JSON file.
    
    These are song names that should NOT have their parentheses stripped.
    The file contains a JSON array of exact song name strings.
    """
    global SONG_NAME_PARENS_EXCEPTIONS
    if SONG_NAME_PARENS_EXCEPTIONS_FILE.exists():
        with open(SONG_NAME_PARENS_EXCEPTIONS_FILE, "r", encoding="utf-8") as f:
            SONG_NAME_PARENS_EXCEPTIONS = set(json.load(f))
        logger.info(f"[PARENS_EXCEPTIONS] Loaded {len(SONG_NAME_PARENS_EXCEPTIONS)} entries from {SONG_NAME_PARENS_EXCEPTIONS_FILE.name}")


def load_all_databases():
    """Load all song databases."""
    load_song_overrides()
    
    load_wrong_matches()
    load_missed_songs()
    load_misidentified_songs()
    load_song_name_parentheses_exceptions()


def lookup_song_override(title, artist=None):
    """
    Exact-match lookup by original name (key) or intl name.
    Returns (orig_key, data_dict) or (None, None).
    If see_artist=True, only matches if artist matches artist_orig or artist_intl.
    """
    found_key = None
    found_data = None
    
    if title in SONG_OVERRIDES:
        found_key = title
        found_data = SONG_OVERRIDES[title]
    elif title in _INTL_INDEX:
        # O(1) lookup via reverse index instead of linear scan
        found_key = _INTL_INDEX[title]
        found_data = SONG_OVERRIDES[found_key]
    
    if found_data and found_data.get('see_artist'):
        # Must match artist
        stored_artists = [found_data.get('artist_orig'), found_data.get('artist_intl')]
        if artist and any(a and a == artist for a in stored_artists):
            return found_key, found_data
        else:
            # Artist mismatch - return no match
            return None, None
    
    return found_key, found_data


def auto_register_song(ori_song, int_song=None, ori_artist=None, int_artist=None, info=None):
    """Auto-register a newly identified song in the overrides JSON (if not already present).
    If the song already exists, merge any missing fields."""
    if not ori_song:
        return
    
    existing_key, existing_data = lookup_song_override(ori_song)
    
    if existing_key and existing_data:
        # Merge missing fields into existing entry
        updated = False
        if int_song and 'intl' not in existing_data:
            existing_data['intl'] = int_song
            updated = True
        if ori_artist and 'artist_orig' not in existing_data:
            existing_data['artist_orig'] = ori_artist
            updated = True
        if int_artist and 'artist_intl' not in existing_data:
            existing_data['artist_intl'] = int_artist
            updated = True
        if info and 'info' not in existing_data:
            existing_data['info'] = info
            updated = True
        if updated:
            save_song_overrides()
            logger.debug(f"[OVERRIDES] Merged fields for existing: {ori_song}")
    else:
        # Create new entry
        entry = {}
        if int_song: entry['intl'] = int_song
        if ori_artist: entry['artist_orig'] = ori_artist
        if int_artist: entry['artist_intl'] = int_artist
        if info: entry['info'] = info
        SONG_OVERRIDES[ori_song] = entry
        save_song_overrides()
        logger.debug(f"[OVERRIDES] Auto-registered: {ori_song}")


def format_missed_entry(key, data):
    """Format a missed_songs.json entry through the display pipeline."""
    return format_display_name(key, data.get('intl'), data.get('artist_orig'), data.get('artist_intl'), data.get('info'))


def get_missed_candidates():
    """Get sorted list of (display_name, key) tuples from missed_songs.json."""
    candidates = []
    for key, data in MISSED_SONGS.items():
        display = format_missed_entry(key, data)
        candidates.append((display, key))
    candidates.sort(key=lambda x: x[0].lower())
    return candidates


def lookup_in_priority_order(title, artist=None):
    """
    Lookup song in priority order: songs.json → missed.json → misidentified.json
    Returns (found_key, data_dict, source) or (None, None, None)
    Source is one of: 'songs', 'missed', 'misidentified'
    """
    # Priority 1: songs.json
    orig_key, override_data = lookup_song_override(title, artist)
    if override_data:
        return orig_key, override_data, 'songs'
    
    # Priority 2: missed.json
    if title in MISSED_SONGS:
        return title, MISSED_SONGS[title], 'missed'
    
    # Priority 3: misidentified.json
    if title in MISIDENTIFIED_SONGS:
        return title, MISIDENTIFIED_SONGS[title], 'misidentified'
    
    return None, None, None