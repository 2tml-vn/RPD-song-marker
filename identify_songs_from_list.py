import asyncio
import sys
import os
import json
import re
import time
import subprocess
import math
from pathlib import Path

# Use local library version
sys.path.insert(0, "./shazamio_lib")
from shazamio import Shazam

# --- Literal Copies from label_marks_complete.py ---

WINDOW_DURATION = 12
MAX_ATTEMPTS = 12

def get_optimal_sliding_windows(gap_size):
    """
    Calculates a list of (start_offset, duration) tuples for sliding windows.
    Matches the logic defined in the specification.
    """
    if gap_size <= WINDOW_DURATION:
        return [(0.0, gap_size)]
    
    # Calculate N (Number of tries)
    # N = clamp(ceil(GapSize / 10), 2, 10)
    n = max(2, min(10, math.ceil(gap_size / 10)))
    
    # Calculate S (Step Size)
    # Step = (GapSize - WINDOW_DURATION) / (N - 1)
    step = (gap_size - WINDOW_DURATION) / (n - 1)
    
    windows = []
    for i in range(n):
        start_offset = i * step
        duration = float(WINDOW_DURATION)
        windows.append((round(start_offset, 3), round(duration, 3)))
    
    return windows

def parse_ts(ts):
    try:
        if ':' in str(ts):
            parts = list(map(float, ts.split(':')))
            if len(parts) == 2: return parts[0] * 60 + parts[1]
            elif len(parts) == 3: return parts[0] * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(ts)
    except: return 0.0

def format_timestamp_for_youtube(total_seconds):
    m, s = divmod(int(round(float(total_seconds))), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"

def format_song_entry(song_info):
    if not song_info: return ""
    
    # Custom Mappings (Expandable)
    mappings = {
        "nightcord - deaya": "キャットラビング - 25時、ナイトコードで。",
        "deaya - nightcord": "キャットラビング - 25時、ナイトコードで。"
    }

    normalized = song_info.strip().lower()
    if normalized in mappings:
        return mappings[normalized]

    if ' - ' in song_info:
        parts = song_info.split(' - ', 1)
        title = re.sub(r'\s*(\(.*\)|\[.*\])$', '', parts[0].strip())
        artist = parts[1].strip().replace('.', '')
        if len(artist) > 60:
            return title
        return f"{title} - {artist}"
    return song_info.strip().replace('.', '')

async def identify_song(shazam, audio_path, current_sec, gap, snippets_dir):
    """
    Attempts to identify a song using a sliding window strategy.
    Returns the found song name or "Unidentified".
    """
    found_name = None
    sliding_windows = get_optimal_sliding_windows(gap)

    for offset, d in sliding_windows:
        print(f"  [DEBUG] Attempt {sliding_windows.index((offset, d)) + 1}/{len(sliding_windows)}: offset +{offset}s, duration {d}s...")
        temp_name = snippets_dir / f"seg_{int(time.time())}.wav"
        # Enhanced ffmpeg params for better Shazam matching
        cmd = [
            "ffmpeg", "-y", "-ss", str(current_sec + offset), "-t", str(d), "-i", str(audio_path),
            "-vn", "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", 
            "-resampler", "soxr",
            "-f", "wav", "-loglevel", "error", str(temp_name)
        ]
        try:
            subprocess.run(cmd, check=True, timeout=15)
            if not temp_name.exists() or temp_name.stat().st_size < 1000:
                continue

            try:
                out = await asyncio.wait_for(shazam.recognize_song(str(temp_name)), timeout=15)
            except (AttributeError, Exception):
                out = await asyncio.wait_for(shazam.recognize(str(temp_name)), timeout=15)
                
            if out and 'track' in out:
                found_name = f"{out['track']['title']} - {out['track']['subtitle']}"
                print(f"    [MATCH] {found_name}")
                break
            else:
                print(f"    [NO MATCH] Window +{offset}s")
        except Exception as e:
            print(f"    [ERROR] {e}")
        finally:
            if temp_name.exists(): temp_name.unlink()
        if found_name: break
    
    return found_name if found_name else "Unidentified"

def find_media_file(library_dir):
    """Finds any video or audio file in the directory starting with 'video' or 'audio'."""
    patterns = ["video.*", "audio.*"]
    extensions = ['.mp4', '.webm', '.mkv', '.m4a', '.mp3', '.wav', '.mov', '.avi']
    for pattern in patterns:
        for p in Path(library_dir).glob(pattern):
            if p.suffix.lower() in extensions:
                return str(p)
    return None

# --- Main Runtime Logic ---

async def main():
    if len(sys.argv) < 2:
        print("Usage: python identify_songs_from_list.py <YOUTUBE_ID>"); return

    vid_id = sys.argv[1]
    work_dir = Path("detections") / vid_id
    json_path = work_dir / "clean_timestamps.json"
    results_txt = work_dir / "identified_list.txt"
    snippets_dir = work_dir / "temp_snippets"
    snippets_dir.mkdir(exist_ok=True)

    if not json_path.exists():
        print(f"Error: No list found at {json_path}"); return

    # Find Media Path
    lib_dir = Path("youtube_library") / vid_id
    media_path = find_media_file(lib_dir)
    if not media_path:
        print(f"Error: No audio or video found in library for {vid_id}. Check youtube_library folder.")
        return

    # Load verified marks
    with open(json_path, 'r', encoding='utf-8') as f:
        marks = json.load(f)
    
    shazam = Shazam(language='ja-JP', endpoint_country='JP', segment_duration_seconds=WINDOW_DURATION)
    sorted_ts = sorted(marks.keys(), key=parse_ts)
    
    # Duration for last gap
    probe = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(media_path)])
    total_dur = float(probe.decode().strip())

    results = {}
    print(f"\n--- SHAZAM MASTER IDENTIFIER: {vid_id} ---")
    print(f"Using media file: {media_path}")
    
    for i, ts in enumerate(sorted_ts):
        current_sec = parse_ts(ts)
        next_sec = parse_ts(sorted_ts[i+1]) if i+1 < len(sorted_ts) else total_dur
        gap = max(WINDOW_DURATION, next_sec - current_sec)
        
        print(f"\n[{i+1}/{len(sorted_ts)}] Processing {ts} (Gap: {gap:.1f}s)...")
        name = await identify_song(shazam, media_path, current_sec, gap, snippets_dir)
        results[ts] = name

    # Final Save
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4, ensure_ascii=False)
    
    with open(results_txt, 'w', encoding='utf-8') as f:
        for ts in sorted_ts:
            f.write(f"{ts} {format_song_entry(results[ts])}\n")
            
    print(f"\nSUCCESS: Results saved to {results_txt}")
    if snippets_dir.exists():
        try: snippets_dir.rmdir()
        except: pass

if __name__ == "__main__":
    asyncio.run(main())