"""
Audio utilities for JRPD marker system.
Handles audio processing, text cleaning, and display formatting.
"""
import re
import queue
import shutil
import subprocess
import sys
import threading
import time
import logging
from pathlib import Path
from config import DISPLAY_FORMAT
from shared_utils import format_timestamp_for_youtube  # Re-export for backward compatibility

logger = logging.getLogger("JRPD")

_BILI_PART_SUFFIX_RE = re.compile(r'^(BV[0-9A-Za-z]+|av\d+|\d+)_p(\d+)$')
_BILI_URL_PART_RE = re.compile(r'bilibili\.com/video/(BV[0-9A-Za-z]+|av\d+)')


def split_bilibili_part(video_id: str):
    """Split a session key like 'BVxxx_p2' into (base_id, part_number).

    Returns (base_id, part) where part is None for bare ids.
    """
    if not video_id:
        return video_id, None
    v = video_id.strip()
    m = _BILI_PART_SUFFIX_RE.match(v)
    if m:
        try:
            return m.group(1), int(m.group(2))
        except ValueError:
            return m.group(1), None
    return v, None


def video_session_key(video_id: str) -> str:
    """Derive a filesystem-safe session key for runs/<key>/.

    - Full Bilibili URLs: '.../video/BVxxx?p=2' -> 'BVxxx_p2' (?p=1/missing -> 'BVxxx').
    - Bare '_pN' keys pass through unchanged.
    - Everything else passes through stripped.
    """
    if not video_id:
        return "default"
    v = video_id.strip()
    if v.startswith("http://") or v.startswith("https://"):
        m = _BILI_URL_PART_RE.search(v)
        if m:
            base = m.group(1)
            pm = re.search(r'[?&]p=(\d+)', v)
            try:
                n = int(pm.group(1)) if pm else 1
            except ValueError:
                n = 1
            return f"{base}_p{n}" if n > 1 else base
        # Non-bilibili URLs: fall back to YouTube v= param when present
        ym = re.search(r'[?&]v=([A-Za-z0-9_-]{11})', v)
        if ym:
            return ym.group(1)
        return v
    return v


def normalize_video_url(video_id: str) -> str:
    """Normalize video identifier to a full URL for yt-dlp.
    Supports YouTube IDs/URLs and Bilibili BV/av IDs/URLs.
    Bilibili multi-part keys ('BVxxx_p2') map to '?p=2' URLs.
    """
    if not video_id:
        return ""
    v = video_id.strip()
    # Already a URL
    if v.startswith("http://") or v.startswith("https://"):
        return v
    # Bilibili multi-part session key: BVxxx_p2 -> .../BVxxx?p=2
    m = _BILI_PART_SUFFIX_RE.match(v)
    if m:
        base, part = m.group(1), m.group(2)
        if base.startswith("BV"):
            return f"https://www.bilibili.com/video/{base}?p={part}"
        if base.startswith("av"):
            return f"https://www.bilibili.com/video/{base}?p={part}"
        return f"https://www.bilibili.com/video/av{base}?p={part}"
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

# aria2c parallel-download args for yt-dlp (--external-downloader aria2c).
# NOTE: _ARIA2C_ARGS_DEFAULT is for YouTube only. Bilibili's CDN
# (upos-hz-mirrorakam) tears down multi-connection transfers mid-flight —
# long cascades of "Got EOF from the server" / "Failed to receive data
# (SEC_E_INVALID_HANDLE, 80090301)" from Windows aria2c's TLS layer, speed
# collapsing from ~10MiB/s to <100KiB/s, then aria2c exiting code 1
# partway through — but only if it gives up. With a big retry budget the
# kill-resume ride actually finishes fast (2026-10-18 test: 52MiB anthology
# audio, exit 0, 70s at 822KiB/s vs ~6-8min on the throttled native path).
# -k1M lets small audio files actually split; --file-allocation=none avoids
# slow pre-allocation on Windows; retry/timeout flags let aria2c recover
# from single-connection drops instead of aborting the whole transfer.
_ARIA2C_ARGS_DEFAULT = (
    "aria2c:-x 8 -s 8 -k 1M --file-allocation=none --check-certificate=false "
    "--retry-wait=3 --max-tries=5 --timeout=60 --connect-timeout=20 "
    "--allow-overwrite=true --auto-file-renaming=false --conditional-get=true"
)

# Kill-resistant aria2c profile for Bilibili. The CDN still decays the
# connection count (CN:8 -> CN:1) and throttles to <1MiB/s per link, but
# --max-tries=100 + --retry-wait=1 make aria2c re-open dropped chunks
# instead of dying (the old --max-tries=5 profile lost that race and
# exited code 1 partway through).
_ARIA2C_ARGS_BILI = (
    "aria2c:-x 8 -s 8 -k 1M --file-allocation=none --check-certificate=false "
    "--retry-wait=1 --max-tries=100 --timeout=30 --connect-timeout=15 "
    "--allow-overwrite=true --auto-file-renaming=false"
)

# Native-downloader retry budget for Bilibili CDN connection kills. Each
# retried read resumes from the .part offset, so a generous count rides
# out a throttled 100MB+ transfer without failing the attempt.
_BILI_NATIVE_RETRIES = 20

# Force machine-parseable per-line progress so it can be streamed to logs
# even when stdout is piped (no TTY). --progress forces output, --newline
# puts each update on its own line instead of \r in-place updates.
_YT_DLP_PROGRESS_ARGS = ["--newline", "--progress"]

# Throttle per-second downloader status lines (aria2c [#...]/yt-dlp
# [download] % updates) so cmd logs show progression without one line/sec.
_PROGRESS_LOG_INTERVAL = 10.0  # seconds between progress lines
_PROGRESS_PCT_STEP = 10.0  # log when percent jumps by this much
_PCT_RE = re.compile(r'(\d+(?:\.\d+)?)%')

# yt-dlp native-downloader mid-read kill:
#   "Got error: <n> bytes read, <m> more expected. Retrying (k/20)..."
# = IncompleteRead/ContentTooShortError: the CDN closed the connection
# after <n> bytes and the downloader immediately resumes from the .part
# offset. Reword it so the cmd log reads as recovery, not an error.
_GOT_ERROR_RE = re.compile(
    r'^(?:\[download\] )?Got error: (\d+) bytes read(?:, (\d+) more expected)?\s*'
    r'\.\s*Retrying \((\d+/\d+)\)\.\.\.$'
)


def _reword_ytdlp_kill(line: str) -> str:
    """Reword yt-dlp's IncompleteRead retry line into plain-language status."""
    m = _GOT_ERROR_RE.match(line)
    if m is None:
        return line
    read, expected, retry = m.group(1), m.group(2), m.group(3)
    read_kib = int(read) // 1024
    if expected:
        pct = int(read) * 100 // (int(read) + int(expected))
        return f"CDN dropped connection at ~{pct}% ({read_kib} KiB); resuming ({retry})"
    return f"CDN dropped connection ({read_kib} KiB); resuming ({retry})"


def _progress_percent(line: str):
    """Return percent as float if this is a progress-status line, else None.

    Returns (is_progress, percent_or_None). Error lines are never progress.
    """
    low = line.lower()
    if "error" in low or "errorcode=" in low or "exception" in low or "aborted" in low:
        return False, None
    if line.startswith("[download]") or line.startswith("[#"):
        m = _PCT_RE.search(line)
        try:
            return True, float(m.group(1)) if m else None
        except ValueError:
            return True, None
    return False, None


def _aria2c_extra_args(is_bilibili: bool = False) -> list:
    """Return yt-dlp external-downloader args for the shared base_cmd.

    Only the YouTube fast path runs base_cmd/aria2c here. Bilibili builds
    dedicated commands instead (_bili_aria2c_cmd on attempts 1-2,
    _native_yt_dlp_cmd on attempts 3-4), so it always gets [] here.
    """
    if is_bilibili:
        logger.debug("[DL] Bilibili: dedicated aria2c/native attempt builders — base_cmd unused")
        return []
    if shutil.which("aria2c"):
        return ["--external-downloader", "aria2c", "--downloader-args", _ARIA2C_ARGS_DEFAULT]
    logger.warning("[DL] aria2c not found on PATH, falling back to native downloader")
    return []


def _remove_partial_downloads(video_dir: Path) -> None:
    """Delete partial/failed download leftovers so the next attempt starts fresh.

    Needed after HTTP 416 (stale resume offset, e.g. aria2c partial resumed
    with a fresh signed Bilibili URL) — retrying resume against the same
    partial just 416s again.
    """
    patterns = ("audio.*", "*.aria2", "*.part", "*.ytdl", "*.temp")
    try:
        for pat in patterns:
            for stale in video_dir.glob(pat):
                if stale.name == ".yt_dlp_cache":
                    continue
                try:
                    if stale.is_file():
                        stale.unlink()
                except OSError:
                    pass
    except Exception:
        pass


def _native_yt_dlp_cmd(video_dir: Path, url: str, is_youtube: bool, retries: int = 10) -> list:
    """Build a yt-dlp command using the native (single-connection) downloader.

    Extra retries let it resume from the .part file and keep going after the
    CDN drops a connection mid-read, instead of failing the whole attempt.
    """
    if is_youtube:
        return [
            "yt-dlp", "-f", "ba/b", "-x", "--audio-format", "best",
            "--remote-components", "ejs:github",
            "--extractor-args", "youtube:player-client=web",
            *_YT_DLP_PROGRESS_ARGS,
            "--retries", str(retries), "--fragment-retries", "10",
            "--concurrent-fragments", "4",
            "-o", str(video_dir / "audio.%(ext)s"),
            url
        ]
    return [
        "yt-dlp", "-f", "ba/b", "-x", "--audio-format", "best",
        "--no-check-certificates",
        "--remote-components", "ejs:github",
        *_YT_DLP_PROGRESS_ARGS,
        "--retries", str(retries), "--fragment-retries", "10",
        "--concurrent-fragments", "4",
        "-o", str(video_dir / "audio.%(ext)s"),
        url
    ]


def _bili_aria2c_cmd(video_dir: Path, url: str) -> list:
    """Build a yt-dlp command using the kill-resistant aria2c profile.

    Bilibili's CDN kills individual connections, but aria2c re-opens them
    (resume via its .aria2 control file — it must NOT be cleaned while
    aria2c attempts remain) and finishes far faster than the throttled
    native single-connection crawl. Callers MUST wipe partials before
    switching to the native downloader: a multi-connection aria2c partial
    is sparse (holes where killed segments never landed), so resuming it
    by byte offset would corrupt the file.
    """
    return [
        "yt-dlp", "-f", "ba/b", "-x", "--audio-format", "best",
        "--no-check-certificates",
        "--remote-components", "ejs:github",
        *_YT_DLP_PROGRESS_ARGS,
        "--external-downloader", "aria2c", "--downloader-args", _ARIA2C_ARGS_BILI,
        "-o", str(video_dir / "audio.%(ext)s"),
        url
    ]


def _native_attempt_timeout(true_duration: int) -> int:
    """Wall-clock budget for one native download attempt (seconds).

    Hours-long Bilibili anthologies mean 100MB+ audio that drains at well
    under 1MiB/s on the throttled CDN. Size the timeout off the true
    duration (128kbps audio needs ~duration/16 of wall time at 500KiB/s,
    so duration/10 leaves ample headroom) instead of a fixed cap, with a
    30-minute ceiling so a stalled transfer can't hang forever.
    """
    if true_duration <= 0:
        return 600
    return min(max(600, 300 + true_duration // 10), 1800)


def _run_yt_dlp(cmd: list, timeout: int = 300):
    """Run yt-dlp, streaming progress lines to the JRPD log (console + file).

    Merges stderr into stdout, logs every non-empty line at INFO with a
    [DL] prefix so download progression is visible in cmd logs, and returns
    an object with .returncode/.stdout/.stderr (stdout==stderr==combined).
    Raises subprocess.TimeoutExpired on timeout (caller handles it).
    """
    from types import SimpleNamespace

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding="utf-8",
        errors="replace",
    )
    line_queue: queue.Queue = queue.Queue()

    def _reader():
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line_queue.put(line)
        finally:
            line_queue.put(None)  # sentinel: reader done

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    start = time.monotonic()
    output_lines: list = []
    returncode = None
    last_progress_log = 0.0
    last_progress_pct: float | None = None
    try:
        while True:
            elapsed = time.monotonic() - start
            remaining = timeout - elapsed
            if remaining <= 0:
                proc.kill()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
                raise subprocess.TimeoutExpired(cmd, timeout)
            try:
                line = line_queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                if proc.poll() is not None and line_queue.empty():
                    break
                continue
            if line is None:  # reader exhausted; drain process exit
                break
            stripped = line.strip()
            if not stripped:
                continue
            stripped = _reword_ytdlp_kill(stripped)
            output_lines.append(stripped)
            is_progress, pct = _progress_percent(stripped)
            if not is_progress:
                # Status / errors -> cmd logs immediately (console is INFO).
                logger.info(f"[DL] {stripped}")
                continue
            # Throttled progress: log at most every INTERVAL, on a PCT_STEP
            # jump, or at 100%. Suppressed ticks go to DEBUG (file log only).
            now = time.monotonic()
            first = last_progress_pct is None
            done = pct is not None and pct >= 100.0
            jumped = (
                pct is not None
                and last_progress_pct is not None
                and pct - last_progress_pct >= _PROGRESS_PCT_STEP
            )
            due = (now - last_progress_log) >= _PROGRESS_LOG_INTERVAL
            if first or done or jumped or due:
                logger.info(f"[DL] {stripped}")
                last_progress_log = now
                if pct is not None:
                    last_progress_pct = pct
            else:
                logger.debug(f"[DL] {stripped}")

        try:
            returncode = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise subprocess.TimeoutExpired(cmd, timeout)
        if returncode is None:
            returncode = proc.returncode if proc.returncode is not None else -1
    finally:
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            if proc.stdout is not None:
                proc.stdout.close()
        except Exception:
            pass

    combined = "\n".join(output_lines)
    return SimpleNamespace(returncode=returncode, stdout=combined, stderr=combined)

# Pre-compiled regex patterns for performance
_CV_TAG_PATTERN = re.compile(r'\s*\([Cc][Vv][.．][^)]*\)')
_MULTI_SPACE_PATTERN = re.compile(r' +')
# Only strip hyphenated tags that look like version/size markers
# (e.g. "-New Arrange Ver.-", "-TV Size-", "-ショート ver.-").
# A generic "-...-" pattern must NOT be used here: it corrupts legitimate
# hyphenated titles such as "KU-RU-KU-RU Cruller!" (eats "-RU-") or
# "Bling-Bang-Bang-Born" (eats "-Bang-"). Single-word segments without a
# version keyword ("-RU-", "-Bang-", "-judgelight-") are always preserved.
_HYPHEN_TAG_PATTERN = re.compile(
    r'\s*-(?=[^-]*\s[^-]*-)[^-]*?(?:\bver\b\.?|\bversion\b|\bTV\s*size\b|\bsize\b|\bshort\b|ショート)[^-]*?-',
    re.IGNORECASE
)
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

    # Download audio: aria2c parallelism for YouTube; Bilibili runs the
    # kill-resistant aria2c profile first (attempts 1-2) with the native
    # single-connection downloader as fallback (attempts 3-4).
    url = normalize_video_url(video_id)
    is_youtube = "youtube.com" in url or "youtu.be" in url
    platform = "YouTube" if is_youtube else "Bilibili"
    is_bilibili = not is_youtube
    ext_dl_args = _aria2c_extra_args(is_bilibili=is_bilibili)
    base_cmd = [
        "yt-dlp", "-f", "bestaudio/best", "-x", "--audio-format", "best",
        "--no-check-certificates",
        "--remote-components", "ejs:github",
        *_YT_DLP_PROGRESS_ARGS,
        *ext_dl_args,
        "-o", str(video_dir / "audio.%(ext)s"),
        url
    ]

    # Track if we should force yt-dlp refresh due to repeated failures
    force_yt_dlp_refresh = False

    # Bilibili: attempts 1-2 run the kill-resistant aria2c profile
    # (resume via its .aria2 control file between them), attempts 3-4
    # fall back to the native single-connection downloader; attempt 4
    # starts fresh (partials wiped — recovers HTTP 416 from a stale
    # resume offset that can never succeed).
    # YouTube: attempts 1-2 are the aria2c parallel fast path, 3-4 native
    # fallback.
    max_attempts = 4

    # Retry with different formats
    for attempt in range(max_attempts):
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

            if is_bilibili:
                if attempt <= 1:
                    # Bilibili fast path: kill-resistant aria2c. Its .aria2
                    # control file is kept intact between these attempts so
                    # a failed run resumes instead of restarting.
                    cmd = _bili_aria2c_cmd(video_dir, url)
                    attempt_timeout = _native_attempt_timeout(true_duration)
                    logger.info(f"[DL] Attempt {attempt + 1}: aria2c kill-resistant for {platform}")
                else:
                    # Bilibili fallback: native single-connection downloader
                    # survives CDN EOF/keep-alive kills without aria2c.
                    # MUST wipe partials first: an aria2c multi-connection
                    # partial is sparse, native resume by offset would
                    # corrupt it.
                    _remove_partial_downloads(video_dir)
                    cmd = _native_yt_dlp_cmd(video_dir, url, is_youtube=False, retries=_BILI_NATIVE_RETRIES)
                    attempt_timeout = _native_attempt_timeout(true_duration)
                    logger.info(f"[DL] Attempt {attempt + 1}: Native downloader for {platform} (single connection, resumable)")
            elif attempt <= 1:
                # YouTube fast path: aria2c parallel download; attempt 2 is a plain retry.
                cmd = base_cmd.copy()
                attempt_timeout = 300
                if attempt == 0:
                    logger.info(f"[DL] Attempt {attempt + 1}: Using base_cmd with web_default client")
                else:
                    logger.info(f"[DL] Attempt {attempt + 1}: Plain retry for {platform}")
            else:  # YouTube attempts 3-4: native downloader fallback (no aria2c).
                # MUST wipe partials first: an aria2c multi-connection
                # partial is sparse (holes), native resume by byte offset
                # would corrupt it. Final attempt wipe also recovers a
                # stale-resume-offset HTTP 416 that can never succeed.
                _remove_partial_downloads(video_dir)
                cmd = _native_yt_dlp_cmd(video_dir, url, is_youtube=True)
                attempt_timeout = 600
                logger.info(f"[DL] Attempt {attempt + 1}: Native fallback (web client, no aria2c)")

            logger.info(f"[DL] Download attempt {attempt + 1}/{max_attempts} for video {video_id}")
            logger.debug(f"[DL] Full command: {' '.join(cmd)}")
            # Streams [download]/[ExtractAudio]/aria2c progress to cmd logs.
            result = _run_yt_dlp(cmd, timeout=attempt_timeout)

            if result.returncode != 0:
                stderr_lower = result.stderr.lower() if result.stderr else ""
                tail = result.stderr[-500:] if result.stderr else "unknown error"
                if "429" in stderr_lower or "too many requests" in stderr_lower:
                    logger.warning(f"[DL] Attempt {attempt + 1}: HTTP 429 Rate Limited by {platform} - IP may be blocked")
                    force_yt_dlp_refresh = True  # Stale yt-dlp often causes 429s
                elif "visitor data" in stderr_lower or "gvs po token" in stderr_lower:
                    logger.warning(f"[DL] Attempt {attempt + 1}: Missing visitor_data for web_safari client")
                    force_yt_dlp_refresh = True  # yt-dlp version issue
                elif "416" in stderr_lower or "requested range" in stderr_lower:
                    # Stale resume offset (aria2c partial + fresh signed URL):
                    # wipe partials now so the next attempt starts from byte 0
                    # instead of 416ing again.
                    _remove_partial_downloads(video_dir)
                    if attempt == max_attempts - 1:
                        logger.warning(f"[DL] Attempt {attempt + 1}: HTTP 416 persists on fresh download - giving up")
                    else:
                        logger.warning(f"[DL] Attempt {attempt + 1}: HTTP 416 range error - partials wiped, retrying fresh")
                elif "aria2c exited" in stderr_lower or "errorcode=" in stderr_lower:
                    logger.warning(
                        f"[DL] Attempt {attempt + 1}: aria2c rejected by {platform} CDN "
                        f"(CDN throttled the multi-connection transfer)"
                    )
                logger.warning(f"[DL] Download attempt {attempt + 1} failed: {tail}")
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
