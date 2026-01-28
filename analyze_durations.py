import json
import os
from pathlib import Path
import subprocess

def parse_ts(ts):
    try:
        if ':' in str(ts):
            parts = list(map(float, ts.split(':')))
            if len(parts) == 2: return parts[0] * 60 + parts[1]
            elif len(parts) == 3: return parts[0] * 3600 + parts[1] * 60 + parts[2]
        return float(ts)
    except: return 0.0

def get_video_duration(audio_path):
    try:
        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
        return float(subprocess.check_output(cmd).decode('utf-8').strip())
    except:
        return 0.0

def main():
    runs_dir = Path("runs")
    success_durations = []
    fail_durations = []

    for video_dir in runs_dir.iterdir():
        if not video_dir.is_dir(): continue
        
        progress_file = video_dir / "progress.json"
        audio_file = video_dir / "audio.m4a"
        
        if not progress_file.exists(): continue
        
        with open(progress_file, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except:
                continue
        
        video_dur = get_video_duration(audio_file) if audio_file.exists() else 0.0
        
        # Sort markers chronologically
        markers = sorted(data.keys(), key=parse_ts)
        
        for i, m in enumerate(markers):
            start = parse_ts(m)
            # Gap is to next marker or end of video
            if i + 1 < len(markers):
                end = parse_ts(markers[i+1])
            else:
                end = video_dur if video_dur > start else start + 120.0 # Default 2m if no dur
            
            gap = end - start
            status = data[m]
            
            if status == "Unidentified" or status == "":
                fail_durations.append(gap)
            elif status != "Processing...":
                success_durations.append(gap)

    print(f"--- Duration Analysis (Entire Library) ---")
    if success_durations:
        print(f"SUCCESSES (Count: {len(success_durations)})")
        print(f"  Avg Gap: {sum(success_durations)/len(success_durations):.1f}s")
        print(f"  Min Gap: {min(success_durations):.1f}s")
        print(f"  Max Gap: {max(success_durations):.1f}s")
    
    if fail_durations:
        print(f"\nFAILURES (Count: {len(fail_durations)})")
        print(f"  Avg Gap: {sum(fail_durations)/len(fail_durations):.1f}s")
        print(f"  Min Gap: {min(fail_durations):.1f}s")
        print(f"  Max Gap: {max(fail_durations):.1f}s")

if __name__ == "__main__":
    main()
