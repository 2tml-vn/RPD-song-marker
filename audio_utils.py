"""
Audio utilities for JRPD marker system.
Handles audio processing, text cleaning, and display formatting.
"""
import re
import subprocess
import sys
import time
import logging
from pathlib import Path
from config import DISPLAY_FORMAT
from shared_utils import format_timestamp_for_youtube  # Re-export for backward compatibility

logger = logging.getLogger("JRPD")

def normalize_video_url(video_id: str) -> str:
    """Normalize video identifier to a full URL for yt-dlp.
    Supports YouTube IDs/URLs and Bilibili BV/av IDs/URLs.
    """
    if not video_id:
        return ""
    v = video_id.strip()
    # Already a URL
    if v.startswith("http://") or v.startswith("https://"):
        return v
    # Bilibili BV id
    if v.startswith("BV") and len(v) >= 10:
        return f"https://www.bilibili.com/video/{v}"
    # Bilibili av id
    if v.startswith("av"):
        return f"https://www.bilibili.com/video/{v}"
    # Bilibili numeric id without av prefix
    if v.isdigit():
        # Could be Bilibili av or YouTube id, assume Bilibili numeric for safety? Try YouTube first? 
        # Heuristic: YouTube ids are 11 chars and contain -_ . We'll default to YouTube for 11-char alnum
        if len(v) == 11:
            return f"https://www.youtube.com/watch?v={v}"
        return f"https://www.bilibili.com/video/av{v}"
    # YouTube 11-char id
    # Simple heuristic: length 11 and contains only youtube allowed chars
    if re.match(r'^[A-Za-z0-9_-]{11}$', v):
        return f"https://www.youtube.com/watch?v={v}"
    # Fallback: try YouTube
    return f"https://www.youtube.com/watch?v={v}"

# Cache for yt-dlp update status (avoids redundant updates)
_yt_dlp_last_update = 0
_yt_dlp_update_interval = 86400  # 24 hours in seconds

# Pre-compiled regex patterns for performance
_CV_TAG_PATTERN = re.compile(r'\s*\([Cc][Vv][.．][^)]*\)')
_MULTI_SPACE_PATTERN = re.compile(r' +')
_HYPHEN_TAG_PATTERN = re.compile(r'\s*-[^-]+-')
_TRAILING_DASH_PATTERN = re.compile(r'\s+-.*$')
_NESTED_PARENS_PATTERN = re.compile(r'\s*\((?:[^()]|\([^()]*\))*\)')
_SQUARE_BRACKETS_PATTERN = re.compile(r'\s*\[[^\]]*\]')
_JP_BRACKETS_PATTERN = re.compile(r'\s*【[^】]*】')
_FEAT_PATTERN = re.compile(r'\s+feat\..*$', re.IGNORECASE)
_DISPLAY_OPTIONAL_PATTERN = re.compile(r'\[([^\]]*)\]')
_DISPLAY_VAR_PATTERN = re.compile(r'\{(\w+)\}')


def clean_artist_name(text):
    """Remove (CV.xxx) tags from artist names (case-insensitive)."""
    if not text:
        return text
    # Only handle regex errors - let other errors propagate
    text = _CV_TAG_PATTERN.sub('', text)
    text = _MULTI_SPACE_PATTERN.sub(' ', text)
    return text.strip()


def strip_extra_info(text):
    """
    Removes all bracket content (...), [...], 【...】, hyphenated -ver- tags,
    " -" and everything after it, and bare 'feat.' suffixes from song titles.
    Handles one level of nested parentheses.
    
    Exception: If the text exactly matches an entry in song_name_parentheses_exceptions.json,
    the text is returned unchanged (parentheses are preserved).
    """
    if not text:
        return text
    
    # Check if this song name is in the exceptions list (parentheses should be preserved)
    # Import here to avoid circular imports (song_db imports from audio_utils)
    from song_db import SONG_NAME_PARENS_EXCEPTIONS
    if text in SONG_NAME_PARENS_EXCEPTIONS:
        logger.debug(f"[strip_extra_info] Preserving parentheses for exception: '{text}'")
        return text
    # 1. Remove -{text}- patterns (e.g., "-New Arrange Ver.-", "-TV Size-", etc.)
    text = _HYPHEN_TAG_PATTERN.sub('', text)
    # 2. Remove " -" and everything after it
    text = _TRAILING_DASH_PATTERN.sub('', text)
    # 3. Remove all (...) content (handles one level of nesting)
    text = _NESTED_PARENS_PATTERN.sub('', text)
    # 4. Remove all [...] content
    text = _SQUARE_BRACKETS_PATTERN.sub('', text)
    # 5. Remove all 【...】 content
    text = _JP_BRACKETS_PATTERN.sub('', text)
    # 6. Remove bare "feat." not in any brackets (e.g., "Song feat.Artist1、Artist2")
    text = _FEAT_PATTERN.sub('', text)
    return text.strip()


def format_display_name(ori_song, int_song=None, ori_artist=None, int_artist=None, info=None):
    """
    Format song name using DISPLAY_FORMAT template.
    Sections in [...] are optional: only included if all {variables} inside have values.
    """
    variables = {
        'ori_song': ori_song or '',
        'int_song': int_song or '',
        'info': info or '',
        'ori_artist': ori_artist or '',
        'int_artist': int_artist or '',
    }

    def replace_optional(match):
        section = match.group(1)
        vars_in_section = _DISPLAY_VAR_PATTERN.findall(section)
        for var_name in vars_in_section:
            if not variables.get(var_name):
                return ''
        for var_name, val in variables.items():
            section = section.replace('{' + var_name + '}', val)
        return section

    result = _DISPLAY_OPTIONAL_PATTERN.sub(replace_optional, DISPLAY_FORMAT)
    for var_name, val in variables.items():
        result = result.replace('{' + var_name + '}', val)
    # Collapse multiple consecutive spaces into one
    result = _MULTI_SPACE_PATTERN.sub(' ', result)
    return result.strip()


def _should_update_yt_dlp(cache_file: Path) -> bool:
    """Check if yt-dlp should be updated based on last update time."""
    global _yt_dlp_last_update
    current_time = time.time()

    # Check if updated within the interval
    if cache_file.exists():
        try:
            last_update_str = cache_file.read_text().strip()
            last_update = float(last_update_str)
            if current_time - last_update < _yt_dlp_update_interval:
                return False
        except (ValueError, IOError):
            pass  # If reading fails, proceed with update

    return True


def _update_yt_dlp(cache_file: Path) -> bool:
    """Update yt-dlp and clear cache. Returns True if successful."""
    try:
        # Update yt-dlp to avoid stale JS challenge solvers
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60
        )
        if result.returncode != 0:
            logger.warning(f"yt-dlp update failed with code {result.returncode}")
            return False

        # Clear cache to refresh challenge solver scripts
        subprocess.run(
            ["yt-dlp", "--rm-cache-dir"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10
        )

        # Record update time
        cache_file.write_text(str(time.time()))
        logger.info("[DL] yt-dlp updated successfully")
        return True
    except subprocess.TimeoutExpired:
        logger.warning("[DL] yt-dlp update timed out")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"[DL] yt-dlp update failed: {e}")
        return False
    except Exception as e:
        logger.error(f"[DL] Unexpected error updating yt-dlp: {e}")
        return False


def _get_duration(video_id: str) -> int:
    """Get video duration in seconds. Returns 0 on failure."""
    try:
        url = normalize_video_url(video_id)
        duration_cmd = [
            "yt-dlp", "--get-duration", "--remote-components", "ejs:github",
            url
        ]
        dur_str = subprocess.check_output(duration_cmd, timeout=30).decode('utf-8').strip()
        parts = list(map(int, dur_str.split(':')))
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif len(parts) == 2:
            return parts[0] * 60 + parts[1]
        elif len(parts) == 1:
            return parts[0]
    except subprocess.TimeoutExpired:
        logger.warning("[DL] Duration check timed out")
    except subprocess.CalledProcessError as e:
        logger.warning(f"[DL] Could not fetch duration: {e}")
    except ValueError as e:
        logger.warning(f"[DL] Could not parse duration: {e}")
    except Exception as e:
        logger.warning(f"[DL] Unexpected error getting duration: {e}")
    return 0


def _validate_audio_file(path: Path, true_duration: int) -> bool:
    """Validate that audio file duration matches expected duration."""
    try:
        probe_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path)
        ]
        local_dur = float(subprocess.check_output(probe_cmd, timeout=10).decode('utf-8').strip())
        if true_duration > 0 and local_dur < (true_duration - 5):
            logger.warning(f"[DL] Audio file {path.name} is shorter than expected ({local_dur}s < {true_duration}s), removing")
            path.unlink()
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.warning(f"[DL] ffprobe timed out for {path.name}")
        return False
    except subprocess.CalledProcessError as e:
        logger.warning(f"[DL] ffprobe failed for {path.name}: {e}")
        return False
    except (ValueError, IOError) as e:
        logger.warning(f"[DL] Could not read duration from {path.name}: {e}")
        return False
    except Exception as e:
        logger.warning(f"[DL] Unexpected error validating {path.name}: {e}")
        return False


def ensure_audio(video_id, video_dir):
    """
    Download or find audio file for a YouTube / Bilibili video.
    Returns path to audio file or None if failed.

    Optimizations:
    - Caches yt-dlp updates (only updates once per 24 hours)
    - Validates existing files before reusing
    - Proper error handling for all operations
    """
    video_dir = Path(video_dir)
    cache_file = video_dir / ".yt_dlp_cache"

    # Ensure cache directory exists
    video_dir.mkdir(parents=True, exist_ok=True)

    # Update yt-dlp if needed (cached)
    if _should_update_yt_dlp(cache_file):
        _update_yt_dlp(cache_file)

    # Get true duration for validation
    true_duration = _get_duration(video_id)
    if true_duration == 0:
        logger.warning("[DL] Could not determine video duration, skipping validation")

    # Check for existing valid audio file
    for ext in ['m4a', 'opus', 'webm', 'mp3', 'mp4', 'ogg']:
        path = video_dir / f"audio.{ext}"
        if path.exists():
            if _validate_audio_file(path, true_duration):
                logger.info(f"[DL] Using existing audio: {path.name}")
                return path
            # File was invalid and removed, continue to download

    # Download audio
    url = normalize_video_url(video_id)
    base_cmd = [
        "yt-dlp", "-f", "bestaudio/best", "-x", "--audio-format", "best",
        "--no-check-certificates",
        "--remote-components", "ejs:github",
        "-o", str(video_dir / "audio.%(ext)s"),
        url
    ]

    # Track if we should force yt-dlp refresh due to repeated failures
    force_yt_dlp_refresh = False
    
    # Retry with different formats
    for attempt in range(3):
        try:
            # Add delay before retry if this isn't the first attempt
            if attempt > 0:
                backoff_delay = 5 * attempt  # 5, 10, 15 seconds
                logger.info(f"[DL] Applying backoff delay: {backoff_delay}s before attempt {attempt + 1}")
                time.sleep(backoff_delay)
            
            # Force yt-dlp refresh if we've had repeated failures (indicates stale version)
            if force_yt_dlp_refresh and _should_update_yt_dlp(cache_file):
                logger.info("[DL] Forcing yt-dlp refresh due to repeated failures")
                _update_yt_dlp(cache_file)
                force_yt_dlp_refresh = False

            if attempt == 0:
                cmd = base_cmd.copy()
                logger.info(f"[DL] Attempt {attempt + 1}: Using base_cmd with web_default client")
            elif attempt == 1:
                cmd = [
                    "yt-dlp", "-f", "bestaudio[protocol=m3u8_native]/bestaudio",
                    "-x", "--audio-format", "best", "--remote-components", "ejs:github",
                    "-o", str(video_dir / "audio.%(ext)s"),
                    f"https://www.youtube.com/watch?v={video_id}"
                ]
                logger.info(f"[DL] Attempt {attempt + 1}: Using m3u8_native protocol fallback")
            else:  # attempt == 2
                cmd = [
                    "yt-dlp", "-f", "ba/b", "-x", "--audio-format", "best",
                    "--remote-components", "ejs:github",
                    "--extractor-args", "youtube:player-client=web",
                    "-o", str(video_dir / "audio.%(ext)s"),
                    f"https://www.youtube.com/watch?v={video_id}"
                ]
                logger.info(f"[DL] Attempt {attempt + 1}: Using web client with extractor-args")

            logger.info(f"[DL] Download attempt {attempt + 1}/3 for video {video_id}")
            logger.debug(f"[DL] Full command: {' '.join(cmd)}")
            result = subprocess.run(cmd, timeout=300, capture_output=True, text=True)

            if result.returncode != 0:
                stderr_lower = result.stderr.lower() if result.stderr else ""
                if "429" in stderr_lower or "too many requests" in stderr_lower:
                    logger.warning(f"[DL] Attempt {attempt + 1}: HTTP 429 Rate Limited by YouTube - IP may be blocked")
                    force_yt_dlp_refresh = True  # Stale yt-dlp often causes 429s
                elif "visitor data" in stderr_lower or "gvs po token" in stderr_lower:
                    logger.warning(f"[DL] Attempt {attempt + 1}: Missing visitor_data for web_safari client")
                    force_yt_dlp_refresh = True  # yt-dlp version issue
                elif "416" in stderr_lower or "requested range" in stderr_lower:
                    logger.warning(f"[DL] Attempt {attempt + 1}: HTTP 416 range error - possible partial download corruption")
                logger.warning(f"[DL] Download attempt {attempt + 1} failed: {result.stderr[:300] if result.stderr else 'unknown error'}")
                continue

            # Check for downloaded file
            for ext in ['m4a', 'opus', 'webm', 'mp3', 'mp4', 'ogg']:
                downloaded = video_dir / f"audio.{ext}"
                if downloaded.exists():
                    logger.info(f"[DL] Downloaded audio: {downloaded.name}")
                    return downloaded

        except subprocess.TimeoutExpired:
            logger.warning(f"[DL] Download attempt {attempt + 1} timed out")
            time.sleep(2)
        except Exception as e:
            logger.error(f"[DL] Download attempt {attempt + 1} failed: {e}")
            time.sleep(2)

    logger.error(f"[DL] All download attempts failed for video {video_id}")
    return None
