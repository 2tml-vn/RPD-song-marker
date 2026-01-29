import os
import sys
import json
import numpy as np
from pathlib import Path
from song_memory_manager import SongMemoryManager
from audio_features import extract_features
import shared_utils
import time
import subprocess
import scipy.io.wavfile as wav
from pydub import AudioSegment

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
    
    try:
        full_audio = AudioSegment.from_file(str(audio_path))
        print(f"Audio loaded successfully: {len(full_audio)/1000:.1f}s")
    except Exception as e:
        print(f"Warning: pydub could not load audio: {e}")
    
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
            # Get duration via ffprobe
            probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
            video_duration = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
            gap_size = video_duration - start_sec
        else:
            gap_size = shared_utils.parse_ts(end_ts) - start_sec
            
        print(f"Learning '{name}' at {start_ts} (Gap: {gap_size:.1f}s)...")
        
        # Get symmetric windows (High-Density 5s strategy)
        windows = shared_utils.get_local_matching_windows(gap_size)
        
        fingerprints = []
        for offset, duration in windows:
            tmp_wav = video_dir / f"learn_tmp_{int(time.time())}.wav"
            # EXTRACT RAW (NO FILTERS) - Matches Phase 2 of identification
            # Use 22050 for ML features
            cmd = [
                "ffmpeg", "-y", "-ss", str(start_sec + offset), "-t", str(duration), "-i", str(audio_path),
                "-vn", "-ar", "22050", "-ac", "1", "-acodec", "pcm_s16le",
                "-f", "wav", "-loglevel", "error", str(tmp_wav)
            ]
            
            try:
                subprocess.run(cmd, check=True)
                
                sr_in, data_in = wav.read(str(tmp_wav))
                y_slice = data_in.astype(np.float32) / 32768.0
                
                # USE NEW ML FEATURES
                fp = extract_features(y_slice, sr_in)
                fingerprints.append(fp)
                time.sleep(0.01)
            except Exception as e:
                print(f"    Failed to process window: {e}")
            finally:
                if tmp_wav.exists(): tmp_wav.unlink()
        
        if fingerprints:
            added, skipped = manager.add_song(name, fingerprints)
            learned_count += 1
            print(f"  Result: Added {added} new signatures, Skipped {skipped} duplicates for '{name}'")

    if learned_count > 0:
        print(f"\nSUCCESS: Learned {learned_count} songs from {video_id}")
        print("\n*** IMPORTANT: New signatures added. Please run: python train_brain.py ***")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python learn_songs.py <VIDEO_ID>")
    else:
        learn_songs(sys.argv[1])