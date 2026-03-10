import math
import re

WINDOW_DURATION = 10.0

def parse_ts(ts):
    try:
        if ':' in str(ts):
            parts = list(map(float, ts.split(':')))
            if len(parts) == 2: return parts[0] * 60 + parts[1]
            elif len(parts) == 3: return parts[0] * 3600 + parts[1] * 60 + parts[2]
        return float(ts)
    except: return 0.0

def format_timestamp_for_youtube(total_seconds):
    try:
        m, s = divmod(int(round(float(total_seconds))), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"
    except:
        return "0:00"

def clean_title(t):
    """
    STRICT MODE: Do not remove anything from the song name.
    """
    if not t: return ""
    return t

def format_song_entry(song_info):
    if not song_info: return ""
    
    parts = re.split(r'\s+[\-\–\—\－]\s+', song_info)
    if len(parts) >= 2:
        title = " - ".join(parts[:-1])
        artist = parts[-1]
        
        # Remove anything in () that contains "CV" (case-insensitive)
        # Handles potential nested parens: \((?:[^()]|\([^()]*\))*[Cc][Vv](?:[^()]|\([^()]*\))*\)
        artist = re.sub(r'\s*\((?:[^()]|\([^()]*\))*[Cc][Vv](?:[^()]|\([^()]*\))*\)', '', artist)
            
        return f"{title} - {artist}"
        
    return song_info

def get_optimal_sliding_windows(gap_size):
    """
    Calculates sliding windows starting at 0.0.
    Order: Starts at ~10% of total windows, goes to the end, then back to the start.
    """
    windows = []
    if gap_size <= WINDOW_DURATION:
        windows.append((0.0, float(round(gap_size, 3))))
    else:
        n = max(2, min(20, math.ceil(gap_size / 7)))
        step = (gap_size - WINDOW_DURATION) / (n - 1)
        for i in range(n):
            start_offset = i * step
            windows.append((round(start_offset, 3), float(WINDOW_DURATION)))
    
    x = len(windows)
    if x > 1:
        start_idx = int(round(x * 0.1))
        # Ensure start_idx is within bounds
        if start_idx >= x: start_idx = x - 1
        
        forward_part = windows[start_idx:]
        backward_part = windows[:start_idx]
        backward_part.reverse()
        
        return forward_part + backward_part
    return windows

def get_local_matching_windows(gap_size):
    """
    Returns high-density 5s windows with 50% overlap (2.5s step).
    """
    local_duration = 5.0
    local_step = 2.5
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

def get_linear_sliding_windows(gap_size):
    """
    Returns windows in strict linear order (Offset 0, 1, 2...).
    """
    windows = []
    if gap_size <= WINDOW_DURATION:
        windows.append((0.0, float(round(gap_size, 3))))
    else:
        n = max(2, min(20, math.ceil(gap_size / 7)))
        step = (gap_size - WINDOW_DURATION) / (n - 1)
        for i in range(n):
            start_offset = i * step
            windows.append((round(start_offset, 3), float(WINDOW_DURATION)))
    return windows
