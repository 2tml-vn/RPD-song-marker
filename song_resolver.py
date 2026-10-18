"""
Song name resolution logic for JRPD marker system.
Resolves detected song names using overrides and external APIs.
"""
import json
import logging
from typing import Optional, Any
from audio_utils import strip_extra_info, clean_artist_name, format_display_name
from song_db import (
    SONG_OVERRIDES, WRONG_MATCHES,
    lookup_song_override, auto_register_song,
    save_song_overrides, lookup_in_priority_order
)

logger = logging.getLogger("JRPD")


def extract_en_title(en_data: Any) -> Optional[str]:
    """
    Extract the English title from Shazam EN API response.
    
    Handles multiple response formats:
    - dict with 'track' key containing 'title'
    - dict with 'title' key directly
    - object with 'title' attribute
    
    Args:
        en_data: Response from shazam_en.track_about()
        
    Returns:
        The title string or None if not found
    """
    if en_data is None:
        return None
    
    # Try dict format with 'track' key
    if isinstance(en_data, dict):
        if 'track' in en_data and isinstance(en_data['track'], dict):
            return en_data['track'].get('title')
        # Try direct 'title' key
        return en_data.get('title')
    
    # Try object attribute
    return getattr(en_data, 'title', None)


async def resolve_song_name(title_clean, artist, track_id=None, shazam_en=None, en_hint=None):
    """
    Resolve a detected song into a formatted display name using overrides and Shazam EN API.
    Also auto-registers new songs into the overrides JSON.
    Returns the formatted display name string, or None if discard flag is set.
    """
    # Raw registration: the engine-reported title is kept as-is and used as the
    # lookup key / registration name. No paren/version stripping on the key.
    # (strip_extra_info is still applied to Shazam EN / en_hint intl titles.)
    artist = clean_artist_name(artist)
    logger.info("[RESOLVE] Input: title_clean='%s' artist='%s' track_id=%s en_hint=%s", title_clean, artist, track_id, en_hint)

    # 1. Check wrong_matches.json — random garbage, discard immediately
    if title_clean in WRONG_MATCHES:
        wm_entry = WRONG_MATCHES[title_clean]
        wm_artist = wm_entry.get('artist') if isinstance(wm_entry, dict) else None
        if not wm_artist or (artist and wm_artist == artist):
            logger.info("[RESOLVE] [1-WRONG_MATCH] '%s' (artist='%s') → returning Unidentified", title_clean, artist)
            return "Unidentified"
        else:
            logger.debug("[RESOLVE] [1-WRONG_MATCH] '%s' found but artist mismatch (expected='%s', got='%s') → continuing", title_clean, wm_artist, artist)
    else:
        logger.debug("[RESOLVE] [1-WRONG_MATCH] '%s' not in wrong_matches", title_clean)

    # 3. Check songs.json, missed.json, misidentified.json in priority order
    orig_key, override_data, source = lookup_in_priority_order(title_clean, artist)
    logger.info("[RESOLVE] [3-OVERRIDE] Priority lookup: orig_key='%s' source='%s' found=%s", orig_key, source, override_data is not None)
    
    if override_data:
        logger.debug("[RESOLVE] [3-OVERRIDE] Entry data: %s", json.dumps(override_data, ensure_ascii=False))

        # Check for discard flag
        if override_data.get('discard'):
            logger.info("[RESOLVE] [3-OVERRIDE] Discard flag set for '%s' (source: %s) → discarding", orig_key, source)
            return None

        # Check for remap in songs.json — follow the remap target
        remap_target = override_data.get('remap')
        if remap_target:
            logger.info("[RESOLVE] [3-OVERRIDE] Found remap in %s: '%s' → '%s'", source, orig_key, remap_target)
            # Follow the remap
            target_key, target_data = lookup_song_override(remap_target)
            if target_data:
                # Check if remap target has discard flag
                if target_data.get('discard'):
                    logger.info("[RESOLVE] [3-OVERRIDE] Remap target '%s' has discard flag → discarding", remap_target)
                    return None
                ori_song = target_key
                int_song = target_data.get('intl')
                info = target_data.get('info')
                ori_artist = target_data.get('artist_orig')
                int_artist = target_data.get('artist_intl')
                result = format_display_name(ori_song, int_song, ori_artist, int_artist, info)
                logger.info("[RESOLVE] [3-OVERRIDE] Remapped to: '%s'", result)
                return result
            else:
                logger.info("[RESOLVE] [3-OVERRIDE] Remap target '%s' not found in songs.json, returning as-is", remap_target)
                return remap_target

        ori_song = orig_key
        
        # Initialize int_song to None - will be set in conditional branches below
        int_song = None
        
        # Resolve international song name
        if override_data.get('intl_override'):
            int_song = override_data.get('intl')
            logger.debug("[RESOLVE] [3-OVERRIDE] intl_override=True → int_song='%s'", int_song)
        else:
            # Use stored intl first, fallback to Shazam EN API
            if 'intl' in override_data:
                int_song = override_data['intl']
                logger.debug("[RESOLVE] [3-OVERRIDE] Using stored intl: '%s'", int_song)
            elif track_id and shazam_en:
                logger.debug("[RESOLVE] [3-OVERRIDE] No stored intl, trying Shazam EN API (track_id=%s)", track_id)
                try:
                    en_data = await shazam_en.track_about(int(track_id))
                    en_title = extract_en_title(en_data)
                    logger.debug("[RESOLVE] [3-OVERRIDE] Shazam EN returned: '%s'", en_title)
                    if en_title and en_title.lower() != ori_song.lower():
                        int_song = strip_extra_info(en_title)
                        logger.debug("[RESOLVE] [3-OVERRIDE] After strip_extra_info: int_song='%s'", int_song)
                        # Skip if stripped intl ended up same as original
                        if int_song and int_song.lower() == ori_song.lower():
                            logger.debug("[RESOLVE] [3-OVERRIDE] intl same as original after strip, discarding")
                            int_song = None
                    else:
                        logger.debug("[RESOLVE] [3-OVERRIDE] Shazam EN title matches original or is empty, skipping")
                except Exception as e:
                    logger.debug("[RESOLVE] [3-OVERRIDE] Shazam EN API failed: %s", e)
            elif en_hint and en_hint.lower() != ori_song.lower():
                int_song = en_hint
                logger.debug("[RESOLVE] [3-OVERRIDE] Using en_hint as intl fallback: '%s'", int_song)
            else:
                logger.debug("[RESOLVE] [3-OVERRIDE] No intl source available (track_id=%s, shazam_en=%s, en_hint=%s)", track_id, shazam_en is not None, en_hint)

        # Resolve artist - use override values if present, otherwise fall back to detected
        ori_artist = override_data.get('artist_orig') or artist
        int_artist = override_data.get('artist_intl')
        info = override_data.get('info')
        
        logger.info("[RESOLVE] [3-OVERRIDE] Resolved: ori_song='%s' intl='%s' info='%s' ori_artist='%s' int_artist='%s'", ori_song, int_song, info, ori_artist, int_artist)

        # Auto-register to merge any newly discovered fields (e.g., intl from Shazam EN)
        auto_register_song(orig_key, int_song, ori_artist, int_artist, info)

        result = format_display_name(ori_song, int_song, ori_artist, int_artist, info)
        logger.info("[RESOLVE] [3-OVERRIDE] Final: '%s'", result)
        return result
    else:
        # No override found — try Shazam EN API for translation
        en_name = None
        if track_id and shazam_en:
            try:
                en_data = await shazam_en.track_about(int(track_id))
                en_title = extract_en_title(en_data)
                logger.debug("[RESOLVE] No override. Shazam EN returned: '%s'", en_title)
                if en_title and en_title.lower() != title_clean.lower():
                    en_name = strip_extra_info(en_title)
            except Exception as e:
                logger.debug("[RESOLVE] No override. Shazam EN API failed: %s", e)

        ori_song = title_clean
        int_song = en_name if en_name and en_name.lower() != title_clean.lower() else None
        # Fallback to en_hint from ACRCloud if Shazam EN wasn't available
        if not int_song and en_hint and en_hint.lower() != title_clean.lower():
            int_song = en_hint
            logger.debug("[RESOLVE] [4-NEW] Using en_hint as intl: '%s'", int_song)
        ori_artist = artist

        logger.info("[RESOLVE] [4-NEW] Auto-register: ori_song='%s' intl='%s' artist='%s'", ori_song, int_song, ori_artist)
        # Auto-register in overrides JSON
        auto_register_song(ori_song, int_song, ori_artist, None, None)

        result = format_display_name(ori_song, int_song, ori_artist, None, None)
        logger.info("[RESOLVE] [4-NEW] Final: '%s'", result)
        return result