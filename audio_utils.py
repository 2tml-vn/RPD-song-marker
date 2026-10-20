"""
Audio utilities for JRPD marker system.
Handles audio processing, text cleaning, and display formatting.
"""
import re
import queue
import json
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import logging
import urllib.error
import urllib.parse
import urllib.request
from http.client import IncompleteRead
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    url = normalize_video_url(video_id)
    if "youtube.com" not in url and "youtu.be" not in url:
        # Bilibili: the pagelist API answers in one ~200 ms call. The old
        # yt-dlp route spun up the EJS challenge machinery for ~5-30 s and
        # the "00\n52" multi-line output then crashed duration parsing.
        return _bili_get_video_duration(video_id)
    try:
        duration_cmd = [
            "yt-dlp", "--get-duration", "--remote-components", "ejs:github",
            url
        ]
        dur_str = subprocess.check_output(duration_cmd, timeout=30).decode('utf-8').strip()
        # yt-dlp sometimes prints extra lines (solver noise) before the
        # duration; it is the last non-empty line.
        lines = [ln for ln in dur_str.splitlines() if ln.strip()]
        if not lines:
            return 0
        dur_str = lines[-1]
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


# ---------------------------------------------------------------------------
# Bilibili native segmented CDN downloader
#
# Ported from j4rviscmd/bilibili-downloader-gui's Rust engine
# (src-tauri/src/utils/downloads.rs + cdn_selector.rs). Bilibili's playurl
# API hands out base_url + backup_url pools per DASH stream, so instead of
# letting yt-dlp / aria2c fight a hostile CDN we:
#   1. resolve bvid/page -> cid -> playurl (no-cookie, fnval=16 DASH;
#      the legacy endpoint works without a wbi signature, 2026-10-20),
#   2. probe every candidate (base + backups) with a small Range GET and
#      keep full-range deliverers ordered first - catches Akamai-style
#      hosts that trim long ranges,
#   3. run an in-process segmented downloader (total/8 clamped 4-32 MB,
#      8 workers) writing each chunk at its offset into a preallocated
#      file, checking 206 + Content-Range start, and verifying the
#      on-disk resume tail before trusting it after a CDN kill,
#   4. rotate candidates on failure: near-zero progress rotates
#      immediately without burning the resume budget; real progress
#      resumes the same host within a small budget (after a tail verify),
#      then rotates. Only *.bilivideo.com hosts get their hostname
#      substituted for a healthy mirror (path + signed query preserved);
#      akamaized.net is never rewritten, P2P mcdn hosts are dropped,
#   5. checkpoint completed segments into an audio.m4s.progress.json
#      sidecar so an interrupted run skips finished segments (a 98%
#      complete file is never thrown away),
#   6. remux the finished stream to audio.m4a (ffmpeg stream-copy) and
#      duration-validate.
#
# The yt-dlp / aria2c ladder in ensure_audio below stays untouched as the
# fallback; this path simply produces audio.m4a when the CDN cooperates.
# ---------------------------------------------------------------------------

_BILI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0"
)
_BILI_REFERER = "https://www.bilibili.com/"
_BILI_API = "https://api.bilibili.com"

# Range-probe: 512 KiB through each candidate before committing to a
# plan. That is still enough for the Content-Range total (size probe)
# and a throughput sample for ranking, while old 4 MiB probes made the
# whole phase take ~45 s on a slow backup host (its bytes all discarded).
_BILI_PROBE_BYTES = 512 * 1024
_BILI_PROBE_TIMEOUT = 6.0

# Segmentation: total/16 clamped to 4-32 MB, 16 workers. Bilibili caps
# per-connection throughput, so more streams = more aggregate speed; 16
# keeps 89 MB on 16 x ~5.6 MB instead of the old 8 x 11 MB ladder. The
# timeout is a per-socket-op stall timer (urllib applies it to connect +
# every read), so a host that stops sending raises instead of hanging.
_BILI_SEG_MIN = 4 * 1024 * 1024
_BILI_SEG_MAX = 32 * 1024 * 1024
_BILI_INFLIGHT = 16
_BILI_STALL_TIMEOUT = 30.0
_BILI_CHUNK = 256 * 1024
_BILI_PROGRESS_INTERVAL = 2.0  # seconds between live progress lines

# Kill/hang recovery per segment. Backoff 200 ms doubling, capped 1.5 s.
# A short read with real progress resumes the same host only after the
# last TAIL_VERIFY on-disk bytes match the edge's bytes at those offsets
# (guards against an edge serving different bytes); at most
# MAX_SLOW_RESUMES such resumes, then the segment rotates CDN. A read
# that produced almost nothing rotates immediately without burning the
# budget or re-verifying anything.
_BILI_BACKOFF_BASE = 0.2
_BILI_BACKOFF_CAP = 1.5
_BILI_TAIL_VERIFY = 64 * 1024
_BILI_MIN_PROGRESS = 64 * 1024
_BILI_MAX_SLOW_RESUMES = 3
_BILI_MAX_CDN_LOOPS = 3  # whole candidate-pool passes per rotation budget

# TLS downgrade mirrors the aria2c ladder's --check-certificate=false:
# only enabled after a real certificate verification failure.
_BILI_SSL_UNVERIFIED = False
_BILI_SSL_CTX: ssl.SSLContext | None = None

_LAST_ROTATE_LOG = [0.0, threading.Lock()]  # [monotonic ts, lock]


def _bili_ssl_context() -> ssl.SSLContext:
    """SSL context for https requests (rebuilt unverified after downgrade)."""
    global _BILI_SSL_CTX
    if _BILI_SSL_CTX is None:
        ctx = ssl.create_default_context()
        if _BILI_SSL_UNVERIFIED:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        _BILI_SSL_CTX = ctx
    return _BILI_SSL_CTX


def _bili_open(url: str, extra_headers: dict | None = None, timeout: float = 10.0):
    """Open a URL with Bilibili UA/Referer headers; returns an HTTPResponse.

    On a certificate-verification failure, downgrades once to unverified
    TLS for the rest of the process (matches --check-certificate=false on
    the aria2c ladder for this machine).
    """
    headers = {"User-Agent": _BILI_UA, "Referer": _BILI_REFERER}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    global _BILI_SSL_CTX
    try:
        if url.lower().startswith("https:"):
            return urllib.request.urlopen(
                req, timeout=timeout, context=_bili_ssl_context())
        return urllib.request.urlopen(req, timeout=timeout)
    except (ssl.SSLError, urllib.error.URLError) as e:
        reason = getattr(e, "reason", e)
        msg = f"{reason}"
        only_once = _BILI_SSL_UNVERIFIED or "certificate" not in msg.lower()
        if only_once:
            raise
        logger.warning("[DL] Bilibili TLS verification failed; "
                       "retrying without verification")
        _BILI_SSL_UNVERIFIED = True
        _BILI_SSL_CTX = None
        return urllib.request.urlopen(
            req, timeout=timeout, context=_bili_ssl_context())


def _bili_backoff(rotation: int) -> float:
    """Backoff seconds for a rotation count: 0.2 * 2^(n-1), capped 1.5 s."""
    n = max(1, rotation)
    return min(_BILI_BACKOFF_BASE * (2 ** (n - 1)), _BILI_BACKOFF_CAP)


def _bili_rotation_log(msg: str) -> None:
    """Log CDN-drop/rotation one-liners, throttled so many concurrent
    workers produce a readable cmd log instead of a CUID-style dump."""
    now = time.monotonic()
    with _LAST_ROTATE_LOG[1]:
        if now - _LAST_ROTATE_LOG[0] < 2.0:
            logger.debug(f"[DL] {msg}")
            return
        _LAST_ROTATE_LOG[0] = now
    logger.info(f"[DL] {msg}")


def _bili_content_range_total(headers) -> int:
    """Total object size from Content-Range (falls back to Content-Length)."""
    cr = headers.get("Content-Range")
    if cr:
        try:
            return int(cr.rsplit("/", 1)[-1].strip())
        except ValueError:
            pass
    try:
        return int(headers.get("Content-Length"))
    except (TypeError, ValueError):
        return 0


def _bili_content_range_start(headers) -> int | None:
    """Start offset of a Content-Range header, or None."""
    cr = headers.get("Content-Range")
    if not cr:
        return None
    spec = cr.split("/", 1)[0].strip()
    if spec.lower().startswith("bytes"):
        spec = spec[len("bytes"):].strip()
    start = spec.split("-", 1)[0].strip()
    try:
        return int(start)
    except ValueError:
        return None


def _bili_is_media_content_type(headers) -> bool:
    """The edge must not answer a media range with JSON/HTML."""
    ct = (headers.get("Content-Type") or "").lower()
    if "application/json" in ct or ct.startswith("text/"):
        return False
    return True


def _bili_host_of(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _bili_is_p2p_cdn_host(host: str) -> bool:
    """P2P CDN hosts (mcdn: e.g. xy1x2.mcdn.bilivideo.cn) are avoided."""
    return "mcdn" in host


def _bili_filter_p2p_hosts(urls: list) -> list:
    """Drop mcdn candidates; if that leaves nothing, keep the originals."""
    kept = [u for u in urls if u and not _bili_is_p2p_cdn_host(_bili_host_of(u))]
    return kept if kept else list(urls)


def _bili_is_bilivideo_com_host(host: str) -> bool:
    return host.endswith(".bilivideo.com")


def _bili_is_mirror_host(host: str) -> bool:
    return (
        _bili_is_bilivideo_com_host(host)
        and host.startswith("upos-sz-mirror")
        and not _bili_is_p2p_cdn_host(host)
    )


def _bili_harvest_mirror_hosts(urls: list) -> list:
    out, seen = [], set()
    for u in urls:
        h = _bili_host_of(u or "")
        if _bili_is_mirror_host(h) and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _bili_substitute_host(url: str, new_host: str) -> str:
    """Rewrite only the hostname (dropping any port). Path plus the signed
    query are preserved - the CDN signature survives the host swap."""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return url
    return urllib.parse.urlunsplit(
        (parts.scheme, new_host, parts.path, parts.query, parts.fragment))


class _BiliHostHealth:
    """Healthy *.bilivideo.com mirror-host map (cdn_selector.rs equivalent).

    Mirror hosts harvested from the candidate pool stay eligible while
    healthy; a host that drops connections is marked unhealthy and, when a
    bilivideo.com candidate referring to it is picked again, its hostname
    is substituted (same path + signed query) for a healthy mirror.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._mirrors: list = []
        self._unhealthy: set = set()

    def seed_mirrors_from_urls(self, urls: list) -> None:
        with self._lock:
            for host in _bili_harvest_mirror_hosts(urls):
                if host not in self._mirrors:
                    self._mirrors.append(host)

    def mark_url_unhealthy(self, url: str) -> None:
        host = _bili_host_of(url)
        if not host:
            return
        with self._lock:
            self._unhealthy.add(host)
            if host in self._mirrors:
                self._mirrors = [m for m in self._mirrors if m != host]

    def record_url_healthy(self, url: str) -> None:
        host = _bili_host_of(url)
        if not host:
            return
        with self._lock:
            self._unhealthy.discard(host)
            if _bili_is_mirror_host(host) and host not in self._mirrors:
                self._mirrors.append(host)

    def resolve_effective_url(self, url: str, rotation: int) -> str:
        """Swap unhealthy bilivideo.com hosts for a healthy mirror, spread
        across the rotation count; every other URL passes through as-is."""
        host = _bili_host_of(url)
        if not host or not _bili_is_bilivideo_com_host(host):
            return url
        with self._lock:
            if host not in self._unhealthy or not self._mirrors:
                return url
            eligible = [m for m in self._mirrors if m not in self._unhealthy]
            if not eligible:
                return url
            target = eligible[rotation % len(eligible)]
        logger.debug("[DL] Host swap: %s -> %s", host, target)
        return _bili_substitute_host(url, target)


def _bili_calculate_segments(total: int, segment_size: int) -> list:
    """Inclusive (start, end) byte ranges covering 0..total-1."""
    segments = []
    start = 0
    while start < total:
        end = min(start + segment_size - 1, total - 1)
        segments.append((start, end))
        start = end + 1
    return segments


def _bili_effective_segment_size(total: int, concurrency: int) -> int:
    """total/concurrency clamped to the 4-32 MB segment window."""
    if total <= 0:
        return 0
    target = max(1, total // max(1, concurrency))
    return max(_BILI_SEG_MIN, min(target, _BILI_SEG_MAX))


def _bili_progress_sidecar_path(path: Path) -> Path:
    return path.with_name(path.name + ".progress.json")


def _bili_load_checkpoint(sidecar: Path):
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("url_path", "total", "segment_size", "completed"):
        if key not in data:
            return None
    if not isinstance(data["completed"], list) or not isinstance(data["total"], int) \
            or not isinstance(data["segment_size"], int) or not isinstance(data["url_path"], str):
        return None
    return data


def _bili_save_checkpoint(sidecar: Path, url_path: str, total: int,
                          segment_size: int, completed: set) -> None:
    data = {
        "url_path": url_path,
        "total": total,
        "segment_size": segment_size,
        "completed": sorted(i for i in completed if isinstance(i, int)),
    }
    tmp = sidecar.with_name(sidecar.name + ".tmp")
    try:
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(sidecar)
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _bili_get_dash_audio_urls(video_id: str):
    """Resolve Bilibili DASH audio CDN candidates for a video id/URL.

    Returns (candidate_urls, url_path) or None. url_path - the signed
    base_url's path - is the checkpoint identity: hosts and the date-signed
    query change between API calls, the path is stable for the stream.
    No auth needed for public videos.
    """
    key = video_session_key(video_id)  # URLs -> 'BVxxx_pN' key form
    base_id, part = split_bilibili_part(key)
    if not base_id:
        return None
    if base_id.startswith("av"):
        params_read = {"aid": base_id[2:]}
        params_bvid = None
    elif base_id.startswith("BV"):
        params_read = {"bvid": base_id}
        params_bvid = base_id
    elif base_id.isdigit():
        params_read = {"aid": base_id}
        params_bvid = None
    else:
        return None

    try:
        q = urllib.parse.urlencode({**params_read, "jsonp": "jsonp"})
        with _bili_open(f"{_BILI_API}/x/player/pagelist?{q}", timeout=10) as resp:
            pl = json.loads(resp.read())
        pages = pl.get("data") or []
        pid = part or 1
        if pid > len(pages):
            logger.warning(
                "[DL] Bilibili page %s exceeds %s pages; native path skipped",
                pid, len(pages))
            return None
        cid = pages[pid - 1]["cid"]
        play_params = {"cid": cid, "fnval": 16, "fourk": 1, "qn": 0,
                       "otype": "json"}
        if params_bvid:
            play_params["bvid"] = params_bvid
        else:
            play_params.update(params_read)
        q = urllib.parse.urlencode(play_params)
        with _bili_open(f"{_BILI_API}/x/player/playurl?{q}", timeout=10) as resp:
            j = json.loads(resp.read())
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.debug("[DL] Native path: Bilibili API call failed: %s", e)
        return None
    if j.get("code") != 0:
        logger.debug("[DL] Native path: playurl rejected (code %s %s)",
                     j.get("code"), j.get("message"))
        return None
    dash = (j.get("data") or {}).get("dash") or {}
    audio = dash.get("audio") or []
    if not audio:
        logger.debug("[DL] Native path: playurl returned no DASH audio")
        return None
    # Best audio track: highest bandwidth (segment id 30280 = 128 kbps m4s).
    best = max(audio, key=lambda a: int(a.get("bandwidth") or 0))
    base = best.get("base_url") or best.get("baseUrl") or ""
    if not base:
        return None
    back = best.get("backup_url") or best.get("backupUrl") or []
    try:
        url_path = urllib.parse.urlsplit(base).path
    except ValueError:
        return None
    if not url_path:
        return None
    candidates = _bili_filter_p2p_hosts([base, *back])
    return candidates, url_path


def _bili_get_video_duration(video_id: str) -> int:
    """Duration (seconds) of the target page from the pagelist API.

    Mirrors _bili_get_dash_audio_urls' id parsing; returns 0 on any
    failure so the caller keeps its old "validation skipped" behavior.
    """
    key = video_session_key(video_id)
    base_id, part = split_bilibili_part(key)
    if not base_id:
        return 0
    if base_id.startswith("av"):
        params = {"aid": base_id[2:]}
    elif base_id.startswith("BV"):
        params = {"bvid": base_id}
    elif base_id.isdigit():
        params = {"aid": base_id}
    else:
        return 0
    try:
        q = urllib.parse.urlencode({**params, "jsonp": "jsonp"})
        with _bili_open(f"{_BILI_API}/x/player/pagelist?{q}", timeout=10) as resp:
            pl = json.loads(resp.read())
        pages = pl.get("data") or []
        pid = part or 1
        if pid > len(pages):
            return 0
        return int(pages[pid - 1].get("duration") or 0)
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.debug("[DL] Bilibili duration API call failed: %s", e)
        return 0


def _bili_probe_candidates(urls: list, health: _BiliHostHealth):
    """Range-probe candidate URLs concurrently; return (ordered_urls, total).

    Full-range deliverers (the edge serves every requested byte) come
    first, ordered by measured throughput; hosts that trim the range or
    fail probe last, in original order. total is the object size from
    Content-Range (the playurl API itself omits it), taken from the first
    successful probe.
    """
    probe = _BILI_PROBE_BYTES
    results: list = []
    lock = threading.Lock()

    def _probe(idx: int, url: str):
        t0 = time.monotonic()
        try:
            with _bili_open(url, {"Range": f"bytes=0-{probe - 1}"},
                            _BILI_PROBE_TIMEOUT) as resp:
                total = _bili_content_range_total(resp.headers)
                if resp.status != 206 or not _bili_is_media_content_type(resp.headers):
                    with lock:
                        results.append((idx, url, False, 0.0, 0))
                    return
                received = 0
                if total > 0:
                    wanted = min(probe, total)
                    while received < wanted:
                        chunk = resp.read(min(_BILI_CHUNK, wanted - received))
                        if not chunk:
                            break
                        received += len(chunk)
                else:
                    # No length known: stream to the probe cap.
                    while received < probe:
                        chunk = resp.read(_BILI_CHUNK)
                        if not chunk:
                            break
                        received += len(chunk)
            elapsed = time.monotonic() - t0
            full_ok = received > 0 and (
                total <= 0 or received >= min(probe, total))
            with lock:
                results.append((idx, url, full_ok, received / max(elapsed, 1e-6),
                                total))
            if full_ok:
                health.record_url_healthy(url)
        except Exception:
            with lock:
                results.append((idx, url, False, 0.0, 0))

    workers = max(1, min(len(urls), 6))
    futures = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for idx, url in enumerate(urls):
            futures.append(ex.submit(_probe, idx, url))
    total = 0
    for _, url, full_ok, _thr, t in sorted(results):
        if full_ok and t > 0:
            total = t
            break

    def _sort_key(r):
        idx, _url, ok, thr, _t = r
        if ok:
            return (0, -thr, idx)
        return (1, 0, idx)

    ordered = [r[1] for r in sorted(results, key=_sort_key)]
    if not ordered:
        ordered = list(urls)
    return ordered, total


def _bili_verify_resume_tail(out_path: Path, url: str, seg_start: int, seg_end: int,
                             on_disk_end: int, tail_verify: int) -> bool:
    """On-disk tail versus the edge's bytes at those offsets.

    Before resuming a segment after a CDN kill, the last (up to)
    tail_verify bytes written for this segment are re-fetched and
    compared - guards against an edge having served different bytes for
    the same offset. Nothing on disk yet is trivially safe to resume.
    """
    verify_len = min(max(on_disk_end - seg_start, 0), tail_verify)
    if verify_len <= 0:
        return True
    verify_start = on_disk_end - verify_len
    try:
        with open(out_path, "rb") as fh:
            fh.seek(verify_start)
            disk = fh.read(verify_len)
        if len(disk) != verify_len:
            return False
        with _bili_open(url, {"Range": f"bytes={verify_start}-{verify_start + verify_len - 1}"},
                        _BILI_STALL_TIMEOUT) as resp:
            if resp.status != 206:
                return False
            if _bili_content_range_start(resp.headers) != verify_start:
                return False
            data = b""
            while len(data) < verify_len:
                chunk = resp.read(verify_len - len(data))
                if not chunk:
                    break
                data += chunk
        return data == disk
    except Exception:
        return False


class _BiliSegmentAbort(Exception):
    """Segment failure after exhausting its rotation budget, or a probe
    serving an unusable response (HTML/JSON where media was expected)."""


def _bili_download_segment(out_path: Path, seg_start: int, seg_end: int,
                           candidate_urls: list, health: _BiliHostHealth,
                           total: int, *, tail_verify: int = _BILI_TAIL_VERIFY,
                           slow_limit: int = _BILI_MAX_SLOW_RESUMES,
                           min_progress: int = _BILI_MIN_PROGRESS,
                           on_bytes=None) -> None:
    """Download one segment with kill/hang recovery (downloads.rs port).

    Rotation policy:
    - 206 + Content-Range start must match the request and the response
      must be media (JSON/HTML answers abort the native path - the
      yt-dlp ladder takes over);
    - mid-stream EOF: near-zero progress rotates immediately; otherwise
      the same host resumes after tail-verify, within slow_limit, then
      rotates;
    - on rotation the failing host is marked unhealthy so bilivideo.com
      candidates referring to it get healthy mirrors substituted (path +
      signed query preserved).
    """
    seg_len = seg_end - seg_start + 1
    if out_path.stat().st_size < total:
        raise _BiliSegmentAbort(f"preallocated file shorter than {total}")
    n_urls = len(candidate_urls)
    url_idx = 0
    rotations = 0
    slow_resumes = 0
    max_rotations = max(1, n_urls * _BILI_MAX_CDN_LOOPS)
    progress = 0  # bytes of this segment already written + verified

    fh = open(out_path, "r+b")
    try:
        while True:
            url = health.resolve_effective_url(candidate_urls[url_idx], rotations)
            pos = seg_start + progress
            remaining = seg_end - pos + 1
            received = 0
            err: Exception | None = None
            try:
                with _bili_open(url, {"Range": f"bytes={pos}-{seg_end}"},
                                _BILI_STALL_TIMEOUT) as resp:
                    status = resp.status
                    cr_start = _bili_content_range_start(resp.headers)
                    if not _bili_is_media_content_type(resp.headers):
                        raise _BiliSegmentAbort(
                            f"CDN probe serving html/json (HTTP {status})")
                    # 206 with the right start is the healthy path; HTTP 200
                    # is acceptable when the whole file was asked for.
                    whole_file = pos == 0 and seg_end == total - 1
                    if status == 206 and cr_start == pos:
                        pass
                    elif status == 200 and whole_file:
                        pass
                    else:
                        err = ValueError(
                            f"HTTP {status}, content-range start {cr_start} != {pos}")
                    if err is None:
                        while remaining > 0:
                            chunk = resp.read(min(_BILI_CHUNK, remaining))
                            if not chunk:
                                break
                            fh.seek(pos + received)
                            fh.write(chunk)
                            received += len(chunk)
                            remaining -= len(chunk)
                            if on_bytes is not None:
                                on_bytes(len(chunk))
            except _BiliSegmentAbort:
                raise
            except Exception as e:
                # URLError / socket.timeout / ConnectionReset / IncompleteRead
                err = e
            fh.flush()
            if err is None and remaining <= 0:
                return  # segment complete
            # Short read or request error: decide the recovery action.
            if received > min_progress and slow_resumes < slow_limit:
                # Real progress: verify the tail, resume the same host.
                if _bili_verify_resume_tail(out_path, url, seg_start, seg_end,
                                            pos + received, tail_verify):
                    progress = pos + received - seg_start
                    slow_resumes += 1
                    time.sleep(_bili_backoff(1))
                    continue
                # Tail mismatch: this edge serves foreign bytes - discard
                # the segment's progress and restart from zero.
                progress = 0
                slow_resumes += 1
                time.sleep(_bili_backoff(1))
                continue
            # Near-zero progress or budget exhausted: rotate candidates and,
            # past the first few, mark this host unhealthy (mirror swap).
            if received > 0:
                logger.debug("[DL] Segment %d-%d: slow resume budget spent after %d KiB; rotating",
                             seg_start, seg_end, received // 1024)
            health.mark_url_unhealthy(url)
            url_idx = (url_idx + 1) % n_urls
            rotations += 1
            progress = 0
            _bili_rotation_log(
                f"CDN dropped a connection at ~{100 * pos // max(total, 1)}%; "
                f"rotating CDN")
            if rotations >= max_rotations:
                raise _BiliSegmentAbort(
                    f"segment {seg_start}-{seg_end} exhausted {max_rotations} "
                    f"CDN rotations ({seg_len // 1024} KiB segment)")
            time.sleep(_bili_backoff(rotations))
    finally:
        try:
            fh.close()
        except Exception:
            pass


class _BiliProgressMeter:
    """Thread-safe, session-scoped byte counter for the live progress line.

    Workers call add() with every chunk they write; base carries the bytes
    the checkpoint had already put on disk so the reported fraction matches
    the file, while speed is computed from this session's bytes only.
    Rotations reset a segment's on-disk progress, so session bytes can
    over-count; the display clamps to the file size.
    """

    def __init__(self, base: int = 0):
        self._lock = threading.Lock()
        self._base = base
        self._done = 0

    def add(self, n: int) -> None:
        with self._lock:
            self._done += n

    def snapshot(self) -> tuple:
        with self._lock:
            return self._base, self._done


def _bili_segmented_download(candidate_urls: list, out_path: Path, total: int,
                             url_path: str, *, segment_size: int | None = None,
                             tail_verify: int | None = None,
                             slow_limit: int | None = None,
                             min_progress: int | None = None,
                             health: _BiliHostHealth | None = None) -> bool:
    """Segmented in-process download of one Bilibili URL into out_path.

    Chunks are written at their offsets into a preallocated file; every
    completed segment is checkpointed to a sidecar so an interrupted run
    skips them instead of starting over. A monitor thread prints a live
    speed/ETA progress line every _BILI_PROGRESS_INTERVAL seconds.
    Returns True only when the file ends exactly total bytes long.
    """
    if not candidate_urls or total <= 0:
        return False
    seg_size = segment_size or _bili_effective_segment_size(total, _BILI_INFLIGHT)
    tail_verify = _BILI_TAIL_VERIFY if tail_verify is None else tail_verify
    slow_limit = _BILI_MAX_SLOW_RESUMES if slow_limit is None else slow_limit
    min_progress = _BILI_MIN_PROGRESS if min_progress is None else min_progress
    if health is None:
        health = _BiliHostHealth()

    segments = _bili_calculate_segments(total, seg_size)
    sidecar = _bili_progress_sidecar_path(out_path)

    existing = out_path.stat().st_size if out_path.exists() else None
    checkpoint = _bili_load_checkpoint(sidecar)
    completed: set = set()
    applicable = (
        checkpoint is not None
        and checkpoint["url_path"] == url_path
        and checkpoint["total"] == total
        and checkpoint["segment_size"] == seg_size
        and existing == total
        and all(isinstance(i, int) and 0 <= i < len(segments)
                for i in checkpoint["completed"])
    )
    if applicable:
        completed = {i for i in checkpoint["completed"] if isinstance(i, int)}
        skipped = sum(segments[i][1] - segments[i][0] + 1
                      for i in completed if 0 <= i < len(segments))
        logger.info("[DL] Checkpoint: %d/%d segments (%.2f MB) already on "
                    "disk - skipping them",
                    len(completed), len(segments), skipped / 1048576)
    else:
        # Fresh plan: preallocate exactly total bytes. Sparse zeros under
        # the holes are fine - the per-offset writes (and, on resume, the
        # tail verifies) replace them.
        with open(out_path, "wb") as fh:
            fh.truncate(total)
        if sidecar.exists():
            try:
                sidecar.unlink()
            except OSError:
                pass
        logger.info(
            "[DL] Segmented CDN download: %.2f MB via %s (+%d backups), "
            "%d x %.2f MB, %d workers",
            total / 1048576, _bili_host_of(candidate_urls[0]),
            max(0, len(candidate_urls) - 1), len(segments),
            seg_size / 1048576, _BILI_INFLIGHT)

    todo = [(i, seg) for i, seg in enumerate(segments) if i not in completed]
    if not todo:
        logger.info("[DL] Checkpoint: all %d segments already complete",
                    len(segments))
    failures: list = []

    # Live progress: segments feed one shared byte counter and a daemon
    # thread prints a speed/ETA line every _BILI_PROGRESS_INTERVALs, so a
    # multi-MB download never sits silent long enough to look hung.
    meter = _BiliProgressMeter(
        base=sum(segments[i][1] - segments[i][0] + 1 for i in completed))
    stop_evt = threading.Event()
    t_start = time.monotonic()

    def _monitor():
        while not stop_evt.wait(_BILI_PROGRESS_INTERVAL):
            base, done = meter.snapshot()
            cur = min(base + done, total)
            speed = done / max(time.monotonic() - t_start, 1e-6)
            eta = (f" ETA {int((total - cur) / speed)}s"
                   if speed > 0 and cur < total else "")
            logger.info("[DL] %s: %.1f/%.1f MB (%d%%) %.2f MB/s%s",
                        out_path.name, cur / 1048576, total / 1048576,
                        100 * cur // max(total, 1), speed / 1048576, eta)

    def _worker(seg):
        i, (s, e) = seg
        _bili_download_segment(
            out_path, s, e, candidate_urls, health, total,
            tail_verify=tail_verify, slow_limit=slow_limit,
            min_progress=min_progress, on_bytes=meter.add)
        return i

    monitor = None
    try:
        if todo:
            monitor = threading.Thread(target=_monitor, daemon=True,
                                       name="bili-dl-progress")
            monitor.start()
        with ThreadPoolExecutor(max_workers=_BILI_INFLIGHT) as ex:
            futures = {ex.submit(_worker, t) for t in todo}
            # as_completed consumes every worker; each one is bounded by its own
            # rotation budget and per-op stall timeout, so a partial failure
            # does not hang the whole download.
            for f in as_completed(futures):
                try:
                    completed.add(f.result())
                except _BiliSegmentAbort as e:
                    failures.append(str(e))
                except Exception as e:
                    failures.append(f"{type(e).__name__}: {e}")
    finally:
        stop_evt.set()
        if monitor is not None:
            monitor.join(timeout=_BILI_PROGRESS_INTERVAL * 2)

    elapsed = time.monotonic() - t_start
    base, done = meter.snapshot()
    cur = min(base + done, total)
    if failures:
        logger.info("[DL] %s incomplete: %.1f/%.1f MB in %.1fs",
                    out_path.name, cur / 1048576, total / 1048576, elapsed)
        logger.warning(
            "[DL] Segmented download failed (%d/%d segments complete); "
            "checkpoint kept for resume", len(completed), len(segments))
        _bili_save_checkpoint(sidecar, url_path, total, seg_size, completed)
        return False
    if todo:
        logger.info("[DL] %s downloaded: %.1f MB in %.1fs (avg %.2f MB/s)",
                    out_path.name, total / 1048576, elapsed,
                    done / max(elapsed, 1e-6) / 1048576)
    try:
        actual = out_path.stat().st_size
    except OSError:
        return False
    if actual != total:
        logger.warning(
            "[DL] audio.m4s size mismatch (%s != %s); native path failed",
            actual, total)
        return False
    try:
        sidecar.unlink()
    except OSError:
        pass
    return True


def _bili_remux_m4s(src: Path, dst: Path) -> bool:
    """Stream-copy the fetched audio track into a clean .m4a.

    Bilibili's DASH audio URL is one self-contained MP4 audio track, so
    ffmpeg remuxes with stream copy. If ffmpeg is unavailable the m4s is
    simply renamed; the duration check in _validate_audio_file gates
    usability either way.
    """
    if shutil.which("ffmpeg"):
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-c", "copy",
                 "-movflags", "+faststart", str(dst)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=120,
            )
            if result.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
                return True
            logger.warning("[DL] ffmpeg remux of %s failed (rc=%s)",
                           src.name, result.returncode)
            if dst.exists():
                try:
                    dst.unlink()
                except OSError:
                    pass
        except (subprocess.TimeoutExpired, OSError) as e:
            logger.warning("[DL] ffmpeg remux error: %s", e)
    try:
        if dst.exists():
            dst.unlink()
        src.replace(dst)
        return True
    except OSError as e:
        logger.warning("[DL] Could not promote %s to %s: %s",
                       src.name, dst.name, e)
        return False


def _bili_native_download_audio(video_id: str, video_dir: Path,
                                true_duration: int) -> Path | None:
    """Native Bilibili audio path: API -> probe -> segmented download.

    Returns the validated audio.m4a path or None so ensure_audio falls
    back to the untouched yt-dlp/aria2c ladder. Nothing on disk is
    deleted here when the CDN misbehaves: an interrupted segmented run
    keeps audio.m4s + its checkpoint for the next invocation.
    """
    info = _bili_get_dash_audio_urls(video_id)
    if not info:
        logger.debug("[DL] Native path: no DASH audio candidates for %s", video_id)
        return None
    candidate_urls, url_path = info
    health = _BiliHostHealth()
    health.seed_mirrors_from_urls(candidate_urls)
    ordered, total = _bili_probe_candidates(candidate_urls, health)
    if not ordered or total <= 0:
        logger.warning("[DL] Native path: CDN probe returned no usable candidates")
        return None
    hosts = ", ".join(_bili_host_of(u) for u in ordered[:3])
    logger.debug("[DL] Probed %d CDN candidates; total %.2f MB; fastest: %s",
                 len(ordered), total / 1048576, hosts)
    out = video_dir / "audio.m4s"
    if not _bili_segmented_download(ordered, out, total, url_path, health=health):
        return None
    m4a = video_dir / "audio.m4a"
    if not _bili_remux_m4s(out, m4a):
        return None
    if not _validate_audio_file(m4a, true_duration):
        return None
    try:
        if out.exists():
            out.unlink()
    except OSError:
        pass
    logger.info("[DL] Native segmented download OK: %s", m4a.name)
    return m4a


def ensure_audio(video_id, video_dir):
    """
    Download or find audio file for a YouTube / Bilibili video.
    Returns path to audio file or None if failed.

    Optimizations:
    - Native Bilibili CDN download first; yt-dlp update is deferred to
      ladder time (once per 24h) so the fast path never waits on pip
    - Validates existing files before reusing
    - Proper error handling for all operations
    """
    video_dir = Path(video_dir)
    cache_file = video_dir / ".yt_dlp_cache"

    # Ensure cache directory exists
    video_dir.mkdir(parents=True, exist_ok=True)

    # Get true duration for validation (Bilibili: one API call, not yt-dlp)
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

    # Bilibili native path first: playurl API -> CDN pool probe ->
    # segmented downloader (ported from bilibili-downloader-gui). It is
    # non-destructive: when the CDN cooperates it returns audio.m4a, and
    # when it fails the checkpoint sidecar keeps whatever finished so a
    # rerun resumes. The yt-dlp/aria2c ladder below is the fallback.
    if is_bilibili:
        try:
            native = _bili_native_download_audio(video_id, video_dir, true_duration)
            if native is not None:
                return native
        except Exception as e:
            logger.warning(f"[DL] Native CDN path errored ({e}); using yt-dlp ladder")
        logger.info("[DL] Native CDN path unavailable/failed - falling back to yt-dlp ladder")

    # yt-dlp is needed only by the ladder below (the native CDN path and
    # the existing-file validation don't touch it), so the once-per-24h
    # update check runs lazily here instead of costing ~6 s on every start.
    if _should_update_yt_dlp(cache_file):
        _update_yt_dlp(cache_file)

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

    # Partial-wipe policy (fixed after the 98%-complete .part was wiped by
    # a retry): partials are KEPT across every attempt and only wiped when
    # the downloader switches fashion - an aria2c multi-connection partial
    # is sparse (holes where killed segments never landed), so resuming it
    # by byte offset with the native downloader would corrupt the file.
    # Plain retries same-downloader resume cleanly (aria2c via its .aria2
    # control file, yt-dlp native via the dense .part offset). Stale
    # resume offsets (HTTP 416) still wipe via the 416 recovery branch.
    # Bilibili: attempts 1-2 aria2c kill-resistant profile, 3-4 native;
    # YouTube: attempts 1-2 aria2c parallel fast path, 3-4 native.
    max_attempts = 4
    prev_attempt_aria2c = False

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
                    prev_attempt_aria2c = True
                    logger.info(f"[DL] Attempt {attempt + 1}: aria2c kill-resistant for {platform}")
                else:
                    # Bilibili fallback: native single-connection downloader
                    # survives CDN EOF/keep-alive kills without aria2c.
                    # Sparse aria2c partials MUST be wiped only on the
                    # downloader switch; a dense native .part resumes by
                    # offset, so consecutive native attempts keep it.
                    if prev_attempt_aria2c:
                        _remove_partial_downloads(video_dir)
                        prev_attempt_aria2c = False
                    cmd = _native_yt_dlp_cmd(video_dir, url, is_youtube=False, retries=_BILI_NATIVE_RETRIES)
                    attempt_timeout = _native_attempt_timeout(true_duration)
                    logger.info(f"[DL] Attempt {attempt + 1}: Native downloader for {platform} (single connection, resumable)")
            elif attempt <= 1:
                # YouTube fast path: aria2c parallel download; attempt 2 is a plain retry.
                cmd = base_cmd.copy()
                attempt_timeout = 300
                prev_attempt_aria2c = True
                if attempt == 0:
                    logger.info(f"[DL] Attempt {attempt + 1}: Using base_cmd with web_default client")
                else:
                    logger.info(f"[DL] Attempt {attempt + 1}: Plain retry for {platform}")
            else:  # YouTube attempts 3-4: native downloader fallback (no aria2c).
                # Sparse aria2c partials are wiped only on the downloader
                # switch; consecutive native attempts (attempt 2 → 3 of this
                # branch) resume their dense .part by offset.
                if prev_attempt_aria2c:
                    _remove_partial_downloads(video_dir)
                    prev_attempt_aria2c = False
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
