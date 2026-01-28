import os
import sys
import json
import numpy as np
from pathlib import Path
from pydub import AudioSegment
from song_memory_manager import SongMemoryManager
from audio_fingerprinter import compute_fingerprint
import shared_utils

def learn_songs(video_id):
    video_dir = Path("runs") / video_id
    unidentified_file = video_dir / "unidentified.json"
    
    if not unidentified_file.exists():
        print(f"Error: {unidentified_file} not found.")
        return

    with open(unidentified_file, "r", encoding="utf-8") as f:
        unidentified_data = json.load(f)

    # Find audio file
    audio_path = None
    for ext in ['m4a', 'mp3', 'webm', 'mp4']:
        p = video_dir / f"audio.{ext}"
        if p.exists():
            audio_path = p
            break
    
    if not audio_path:
        print(f"Error: Audio file not found in {video_dir}")
        return

    print(f"Loading audio: {audio_path}")
    audio = AudioSegment.from_file(str(audio_path))
    # Normalize to standard sr for fingerprinting
    audio = audio.set_frame_rate(22050).set_channels(1)
    sr = 22050
    
    manager = SongMemoryManager()
    
    learned_count = 0
    for start_ts, info in unidentified_data.items():
        name = info.get("name")
        if not name:
            continue
            
        end_ts = info.get("end")
        start_sec = shared_utils.parse_ts(start_ts)
        
        # Calculate gap size
        if end_ts == "END":
            gap_size = audio.duration_seconds - start_sec
        else:
            gap_size = shared_utils.parse_ts(end_ts) - start_sec
            
        print(f"Learning '{name}' at {start_ts} (Gap: {gap_size:.1f}s)...")
        
        # Get symmetric windows
        windows = shared_utils.get_optimal_sliding_windows(gap_size)
        
        fingerprints = []
        for offset, duration in windows:
            start_ms = int((start_sec + offset) * 1000)
            end_ms = int((start_sec + offset + duration) * 1000)
            clip = audio[start_ms:end_ms]
            
            # Convert to numpy array
            y_slice = np.array(clip.get_array_of_samples(), dtype=np.float32) / 32768.0
            
            if len(y_slice) > 0:
                fp = compute_fingerprint(y_slice, sr)
                fingerprints.append(fp)
        
        if fingerprints:
            manager.add_song(name, fingerprints)
            learned_count += 1
            print(f"  Added {len(fingerprints)} signatures for '{name}'")

    print(f"\nSUCCESS: Learned {learned_count} songs from {video_id}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python learn_songs.py <VIDEO_ID>")
    else:
        learn_songs(sys.argv[1])