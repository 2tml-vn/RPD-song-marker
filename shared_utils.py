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

def format_song_entry(song_info):
    if not song_info: return ""
    
    # Handle standard dash splitting
    # Supporting various dash types: -, –, —, －
    parts = re.split(r'\s*[\-\–\—\－]\s*', song_info, 1)
    
    if len(parts) == 2:
        title = parts[0].strip()
        artist = parts[1].strip()
        
        # If artist name is absurdly long, return only the title
        if len(artist) > 60:
            return title
            
        return f"{title} - {artist}"
        
    return song_info.strip()

def get_optimal_sliding_windows(gap_size):
    """
    Calculates sliding windows starting at 0.0 and adds a final full-gap attempt.
    Reorders attempts to prioritize the Center first, then outward, with edges last.
    """
    windows = []
    
    # 1. Generate Standard Linear Windows
    if gap_size <= WINDOW_DURATION:
        windows.append((0.0, float(round(gap_size, 3))))
    else:
        # High density (divide by 7)
        n = max(2, min(20, math.ceil(gap_size / 7)))
        step = (gap_size - WINDOW_DURATION) / (n - 1)
        for i in range(n):
            start_offset = i * step
            windows.append((round(start_offset, 3), float(WINDOW_DURATION)))
    
    # 2. Reorder: Center-Out Strategy
    if len(windows) > 2:
        mid_index = len(windows) // 2
        # Split into Center, Left-of-Center, Right-of-Center
        center = windows[mid_index]
        left_side = windows[:mid_index]
        right_side = windows[mid_index+1:]
        
        # Interleave left and right moving outwards from center
        reordered = [center]
        
        # Reverse left side to go 3, 2, 1... and Keep right side 5, 6, 7...
        left_side.reverse()
        
        max_len = max(len(left_side), len(right_side))
        for i in range(max_len):
            if i < len(left_side): reordered.append(left_side[i])
            if i < len(right_side): reordered.append(right_side[i])
            
        windows = reordered

    # 3. FINAL ATTEMPT: The full gap duration (Always last)
    # Only add full gap if it's different from the windows we just made (i.e. gap > WINDOW_DURATION)
    if gap_size > WINDOW_DURATION:
        full_gap_win = (0.0, round(float(gap_size), 3))
        windows.append(full_gap_win)
        
    return windows