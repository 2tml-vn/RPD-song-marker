"""
Song identification logic for JRPD marker system.
Handles Shazam and ACRCloud identification.
"""
import asyncio
import subprocess
import time
import logging
from pathlib import Path
from typing import Optional

import acrcloud
from config import ACR_CONFIG
from audio_utils import strip_extra_info
from song_resolver import resolve_song_name
import shared_utils

logger = logging.getLogger("JRPD")


class IdentificationError(Exception):
    """Custom exception for song identification errors."""
    pass


class ShazamIdentificationError(IdentificationError):
    """Exception for Shazam-specific identification errors."""
    pass


class ACRCloudIdentificationError(IdentificationError):
    """Exception for ACRCloud-specific identification errors."""
    pass


async def _extract_audio_segment(
    audio_path: Path,
    current_sec: float,
    offset: float,
    duration: float,
    output_path: Path
) -> bool:
    """
    Extract an audio segment using ffmpeg.

    Args:
        audio_path: Path to source audio file
        current_sec: Start position in seconds
        offset: Offset from current_sec
        duration: Duration of segment
        output_path: Path for output file

    Returns:
        True if successful, False otherwise
    """
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(current_sec + offset),
        "-t", str(duration),
        "-i", str(audio_path),
        "-vn",
        "-loglevel", "error",
        str(output_path)
    ]

    try:
        result = subprocess.run(cmd, timeout=60, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"[FFMPEG] Error extracting segment: {result.stderr[:200] if result.stderr else 'unknown error'}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"[FFMPEG] Timeout extracting segment at {current_sec + offset}s")
        return False
    except FileNotFoundError:
        logger.error("[FFMPEG] ffmpeg not found in PATH")
        return False
    except Exception as e:
        logger.error(f"[FFMPEG] Unexpected error: {e}")
        return False


async def _identify_with_shazam(
    shazam,
    shazam_en,
    temp_name: Path,
    current_sec: float,
    offset: float,
    audio_path: Path,
    sliding_windows: list,
    i: int
) -> Optional[str]:
    """
    Attempt song identification using Shazam.

    Returns:
        Song name if identified, None otherwise
    """
    # Extract audio segment
    if not await _extract_audio_segment(
        audio_path, current_sec, offset, sliding_windows[i][1], temp_name
    ):
        return None
    
    # Verify the extracted file exists and has content
    if not temp_name.exists():
        logger.error(f" [Shazam] Extracted file does not exist: {temp_name}")
        return None
    
    file_size = temp_name.stat().st_size
    if file_size == 0:
        logger.error(f" [Shazam] Extracted file is empty: {temp_name}")
        return None
    
    if file_size < 1000:
        logger.warning(" [Shazam] Extracted file is very small (%d bytes): %s", file_size, temp_name)
    else:
        logger.debug(" [Shazam] Extracted file size: %d bytes", file_size)

    try:
        # Recognize with Shazam (let shazamio handle retries via aiohttp_retry)
        out = await shazam.recognize(str(temp_name))

        if out and 'track' in out:
            track = out['track']
            logger.info(" [RAW SHAZAM] %s - %s (track_id=%s)", track['title'], track['subtitle'], track.get('key'))

            title_clean = shared_utils.clean_title(track['title'])
            artist = track['subtitle']
            track_id = track.get('key')

            logger.debug(" [SHAZAM] Calling resolve_song_name with title_clean='%s' artist='%s' track_id=%s", title_clean, artist, track_id)
            full_match_name = await resolve_song_name(title_clean, artist, track_id, shazam_en)

            # Check for discard (None return)
            if full_match_name is None:
                logger.info(" [DISCARDED - SHAZAM] '%s' marked as discard, continuing...", title_clean)
                return None

            logger.info(" [MATCH - SHAZAM] %s", full_match_name)
            return full_match_name
        else:
            logger.debug(" [SHAZAM] No track in response")
            return None
            
    except KeyError as e:
        logger.debug(" [Shazam] Missing key in response: %s", e)
        return None
    except Exception as e:
        error_type = type(e).__name__
        error_str = str(e)
        
        # Enhanced diagnostic logging
        if "semaphore timeout" in error_str.lower():
            logger.error(f" [Shazam] NETWORK ERROR: Connection timeout to Shazam servers")
            logger.error(f" [Shazam] DIAGNOSIS: Possible causes:")
            logger.error(f" [Shazam]   1. Internet connectivity issue (check network/firewall)")
            logger.error(f" [Shazam]   2. Shazam server is down or overloaded")
            logger.error(f" [Shazam]   3. DNS resolution failure for amp.shazam.com")
            logger.error(f" [Shazam]   4. VPN/Proxy blocking the connection")
        elif "name or service not known" in error_str.lower() or "getaddrinfo" in error_str.lower():
            logger.error(f" [Shazam] DNS ERROR: Cannot resolve amp.shazam.com")
        elif "connection refused" in error_str.lower():
            logger.error(f" [Shazam] CONNECTION REFUSED: Shazam server rejected the connection")
        elif "timeout" in error_str.lower():
            logger.error(f" [Shazam] TIMEOUT: Request took too long to complete")
        else:
            logger.error(f" [Shazam] Error type: {error_type}")
        
        logger.error(f" [Shazam] Error: {e}")
        return None


async def _identify_with_acrcloud(
    shazam_en,
    temp_name: Path,
    current_sec: float,
    offset: float,
    audio_path: Path,
    sliding_windows: list,
    i: int,
    collect_raw: Optional[list] = None,
) -> Optional[str]:
    """
    Attempt song identification using ACRCloud.

    Args:
        collect_raw: optional list that each raw acr_result dict is appended
            to (even when DB resolve fails/discards), so callers such as the
            /acr_identify endpoint can surface full ACRCloud details.

    Returns:
        Song name if identified, None otherwise
    """
    # Extract audio segment
    if not await _extract_audio_segment(
        audio_path, current_sec, offset, sliding_windows[i][1], temp_name
    ):
        return None

    try:
        acr_result = await acrcloud.recognize(
            str(temp_name),
            access_key=ACR_CONFIG['access_key'],
            access_secret=ACR_CONFIG['access_secret'],
            host=ACR_CONFIG['host']
        )

        if acr_result:
            if collect_raw is not None:
                try:
                    collect_raw.append(acr_result)
                except Exception:
                    pass
            logger.info(
                " [RAW ACRCLOUD] (window %d/%d @ %.1fs) %s - %s (en: %s)",
                i + 1, len(sliding_windows), current_sec + offset,
                acr_result['title'], acr_result['artist'], acr_result.get('en_title'),
            )

            title_clean = shared_utils.clean_title(acr_result['title'])
            artist = acr_result['artist']
            en_hint = strip_extra_info(acr_result.get('en_title')) if acr_result.get('en_title') else None

            logger.debug(" [ACRCloud] Calling resolve_song_name with title_clean='%s' artist='%s' en_hint=%s", title_clean, artist, en_hint)
            acr_match = await resolve_song_name(title_clean, artist, None, shazam_en, en_hint=en_hint)

            # Check for discard (None return)
            if acr_match is None:
                logger.info(" [DISCARDED - ACRCLOUD] '%s' marked as discard, continuing...", title_clean)
                return None

            logger.info(" [MATCH - ACRCLOUD] %s", acr_match)
            return acr_match
        else:
            logger.debug(" [ACRCloud] No result from recognition")
            return None
    except KeyError as e:
        logger.debug(" [ACRCloud] Missing key in response: %s", e)
    except Exception as e:
        error_type = type(e).__name__
        error_str = str(e)
        
        # Diagnose the specific error
        if "semaphore timeout" in error_str.lower():
            logger.error(f" [ACRCloud] NETWORK ERROR: Connection timeout")
            logger.error(f" [ACRCloud] DIAGNOSIS: Possible causes:")
            logger.error(f" [ACRCloud]   1. Internet connectivity issue")
            logger.error(f" [ACRCloud]   2. ACRCloud server is down or overloaded")
        elif "name or service not known" in error_str.lower() or "getaddrinfo" in error_str.lower():
            logger.error(f" [ACRCloud] DNS ERROR: Cannot resolve ACRCloud host")
        elif "connection refused" in error_str.lower():
            logger.error(f" [ACRCloud] CONNECTION REFUSED")
        elif "timeout" in error_str.lower():
            logger.error(f" [ACRCloud] TIMEOUT: Request took too long")
        else:
            logger.error(f" [ACRCloud] Error type: {error_type}")
        
        logger.error(f" [ACRCloud] Error: {e}")

    return None


async def identify_song(
    shazam,
    shazam_en,
    audio_path: Path,
    current_sec: float,
    gap: float,
    snippets_dir: Path,
    is_last_segment: bool = False,
    target: str = ""
) -> str:
    """
    Identify a song from an audio segment using Shazam (primary) and ACRCloud (fallback).

    Args:
        shazam: Shazam client instance
        shazam_en: Shazam EN client for international names
        audio_path: Path to the source audio file
        current_sec: Current position in seconds
        gap: Duration of the unidentified segment
        snippets_dir: Directory for temporary audio snippets
        is_last_segment: Whether this is the last segment
        target: Target timestamp string for logging purposes

    Returns:
        The formatted display name string or "Unidentified"
    """
    try:
        sliding_windows = shared_utils.get_optimal_sliding_windows(gap)
    except Exception as e:
        logger.error(f"Error calculating sliding windows: {e}")
        return "Unidentified"

    logger.debug("[IDENTIFY] Sliding windows: %s", sliding_windows)

    # Phase 1: Shazam Identification
    logger.info("[IDENTIFY] Phase 1: Shazam Identification")

    for i, (offset, d) in enumerate(sliding_windows):
        logger.info(" [Shazam] Window %d/%d: extract @ %.1fs (offset +%.1fs, dur %.1fs)", i+1, len(sliding_windows), current_sec + offset, offset, d)

        temp_name = snippets_dir / f"seg_{int(time.time())}_shazam.wav"
        try:
            result = await _identify_with_shazam(
                shazam, shazam_en, temp_name, current_sec, offset, audio_path, sliding_windows, i
            )
            if result:
                logger.info(" [Shazam] SUCCESS on window %d: %s", i+1, result)
                return result
            else:
                logger.debug(" [Shazam] No match on window %d", i+1)
        finally:
            # Cleanup temp file
            if temp_name.exists():
                try:
                    temp_name.unlink()
                except OSError as e:
                    logger.warning("Could not remove temp file %s: %s", temp_name, e)

    # Phase 2: ACRCloud Fallback
    logger.info("[IDENTIFY] Phase 2: ACRCloud Fallback")

    for i, (offset, d) in enumerate(sliding_windows):
        logger.info(" [ACRCloud] Window %d/%d: extract @ %.1fs (offset +%.1fs, dur %.1fs)", i+1, len(sliding_windows), current_sec + offset, offset, d)

        temp_name = snippets_dir / f"seg_{int(time.time())}_acr.wav"
        try:
            result = await _identify_with_acrcloud(
                shazam_en, temp_name, current_sec, offset, audio_path, sliding_windows, i
            )
            if result:
                logger.info(" [ACRCloud] SUCCESS on window %d: %s", i+1, result)
                return result
            else:
                logger.debug(" [ACRCloud] No match on window %d", i+1)
        finally:
            # Cleanup temp file
            if temp_name.exists():
                try:
                    temp_name.unlink()
                except OSError as e:
                    logger.warning("Could not remove temp file %s: %s", temp_name, e)

    logger.info(" [FINAL RESULT] Unidentified")
    return "Unidentified"
