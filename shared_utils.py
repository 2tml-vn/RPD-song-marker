import math
import re
import logging

logger = logging.getLogger("JRPD")

# Pre-compiled regex patterns for performance
_SONG_ENTRY_SPLIT_PATTERN = re.compile(r'\s+[\-\–\—\－]\s+')
_CV_IN_PARENS_PATTERN = re.compile(r'\s*\((?:[^()]|\([^()]*\))*[Cc][Vv](?:[^()]|\([^()]*\))*\)')

# Duration of each sliding window in seconds (10 seconds)
WINDOW_DURATION = 10.0

# Minimum number of windows to generate (ensures at least 2 windows for coverage)
MIN_WINDOWS = 2

# Maximum number of windows to generate (limits computation for large gaps)
MAX_WINDOWS = 10

# Divisor for calculating window count (gap_size / 7 determines base window count)
WINDOW_DIVISOR = 7


def parse_ts(ts):
    """
    Parse a timestamp string into seconds.

    Args:
        ts: Timestamp string in format "M:SS", "H:MM:SS", or numeric seconds

    Returns:
        Total seconds as float, or 0.0 on error
    """
    try:
        if ':' in str(ts):
            parts = list(map(float, ts.split(':')))
            if len(parts) == 2:
                return parts[0] * 60 + parts[1]
            elif len(parts) == 3:
                return parts[0] * 3600 + parts[1] * 60 + parts[2]
            else:
                logger.warning(f"Invalid timestamp format: {ts}")
                return 0.0
        return float(ts)
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse timestamp '{ts}': {e}")
        return 0.0


def format_timestamp_for_youtube(total_seconds):
    """
    Convert seconds to YouTube timestamp format (M:SS or H:MM:SS).

    Args:
        total_seconds: Time in seconds

    Returns:
        Formatted timestamp string
    """
    try:
        m, s = divmod(int(round(float(total_seconds))), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
    except (ValueError, TypeError, OverflowError) as e:
        logger.warning(f"Error formatting timestamp {total_seconds}: {e}")
        return "0:00"


def clean_title(t):
    """
    STRICT MODE: Do not remove anything from the song name.

    Args:
        t: Title string

    Returns:
        Cleaned title string
    """
    if not t:
        return ""
    return t


def format_song_entry(song_info):
    """
    Format a song entry by splitting on separator and cleaning artist.

    Args:
        song_info: Song info string in format "Title - Artist"

    Returns:
        Formatted song string
    """
    if not song_info:
        return ""

    try:
        parts = _SONG_ENTRY_SPLIT_PATTERN.split(song_info)
        if len(parts) >= 2:
            title = " - ".join(parts[:-1])
            artist = parts[-1]

            # Remove anything in () that contains "CV" (case-insensitive)
            # Handles potential nested parens
            artist = _CV_IN_PARENS_PATTERN.sub('', artist)

            return f"{title} - {artist}"
    except re.error as e:
        logger.error(f"Regex error in format_song_entry: {e}")
    except Exception as e:
        logger.error(f"Unexpected error in format_song_entry: {e}")

    return song_info


def get_optimal_sliding_windows(gap_size: float) -> list:
    """
    Calculates sliding windows starting at 0.0.
    Order: Starts at ~10% of total windows, goes to the end, then back to the start.

    Strategy:
    1. Generate evenly-spaced windows across the gap
    2. Prioritize windows starting at 10% through the gap
    3. Fall back to earlier windows if initial attempts fail

    Args:
        gap_size: Duration of the unidentified segment in seconds

    Returns:
        List of (start_offset, duration) tuples in priority order
    """
    windows = []

    try:
        if gap_size <= WINDOW_DURATION:
            windows.append((0.0, float(round(gap_size, 3))))
        else:
            # Clamp window count between MIN_WINDOWS (2) and MAX_WINDOWS (10)
            n = max(MIN_WINDOWS, min(MAX_WINDOWS, math.ceil(gap_size / WINDOW_DIVISOR)))
            step = (gap_size - WINDOW_DURATION) / (n - 1) if n > 1 else 0

            for i in range(n):
                start_offset = i * step
                windows.append((round(start_offset, 3), float(WINDOW_DURATION)))

        x = len(windows)
        if x > 1:
            start_idx = int(round(x * 0.1))
            # Ensure start_idx is within bounds
            if start_idx >= x:
                start_idx = x - 1

            forward_part = windows[start_idx:]
            backward_part = windows[:start_idx]
            backward_part.reverse()

            return forward_part + backward_part

        return windows
    except (ValueError, TypeError, OverflowError) as e:
        logger.error(f"Error calculating sliding windows for gap {gap_size}: {e}")
        # Return a safe default
        return [(0.0, float(min(gap_size, WINDOW_DURATION)))]
    except Exception as e:
        logger.error(f"Unexpected error calculating sliding windows for gap {gap_size}: {e}")
        return [(0.0, float(min(gap_size, WINDOW_DURATION)))]


def get_local_matching_windows(gap_size: float) -> list:
    """
    Returns high-density 5s windows with 50% overlap (2.5s step).

    Args:
        gap_size: Duration of the unidentified segment in seconds

    Returns:
        List of (start_offset, duration) tuples
    """
    local_duration = 5.0
    local_step = 2.5

    try:
        if gap_size <= local_duration:
            return [(0.0, float(round(gap_size, 3)))]

        windows = []
        current = 0.0
        while current + local_duration <= gap_size:
            windows.append((round(current, 3), local_duration))
            current += local_step

        last_start = max(0.0, gap_size - local_duration)
        if not windows or last_start > windows[-1][0] + 0.1:
            windows.append((round(last_start, 3), local_duration))

        return windows
    except (ValueError, TypeError, OverflowError) as e:
        logger.error(f"Error calculating local matching windows for gap {gap_size}: {e}")
        return [(0.0, float(min(gap_size, local_duration)))]
    except Exception as e:
        logger.error(f"Unexpected error calculating local matching windows for gap {gap_size}: {e}")
        return [(0.0, float(min(gap_size, local_duration)))]


def get_linear_sliding_windows(gap_size: float) -> list:
    """
    Returns windows in strict linear order (Offset 0, 1, 2...).

    Args:
        gap_size: Duration of the unidentified segment in seconds

    Returns:
        List of (start_offset, duration) tuples
    """
    windows = []

    try:
        if gap_size <= WINDOW_DURATION:
            windows.append((0.0, float(round(gap_size, 3))))
        else:
            n = max(2, min(20, math.ceil(gap_size / 7)))
            step = (gap_size - WINDOW_DURATION) / (n - 1) if n > 1 else 0

            for i in range(n):
                start_offset = i * step
                windows.append((round(start_offset, 3), float(WINDOW_DURATION)))

        return windows
    except (ValueError, TypeError, OverflowError) as e:
        logger.error(f"Error calculating linear sliding windows for gap {gap_size}: {e}")
        return [(0.0, float(min(gap_size, WINDOW_DURATION)))]
    except Exception as e:
        logger.error(f"Unexpected error calculating linear sliding windows for gap {gap_size}: {e}")
        return [(0.0, float(min(gap_size, WINDOW_DURATION)))]
