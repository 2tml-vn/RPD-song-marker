import os
import sys
import json
import numpy as np
from pathlib import Path
from song_memory_manager import SongMemoryManager
from audio_fingerprinter import compute_fingerprint
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
    
    # Use pydub for potential normalization or format handling if needed by spec
    # Though we mostly use ffmpeg for snippets, the spec specifically asked for pydub utilization.
    # We will load it once to ensure it works and can be used for global properties.
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
        
        # Get symmetric windows (Center-Out strategy from shared_utils)
        windows = shared_utils.get_optimal_sliding_windows(gap_size)
        
        fingerprints = []
        for offset, duration in windows:
            tmp_wav = video_dir / f"learn_tmp_{int(time.time())}.wav"
            # EXTRACT RAW (NO FILTERS) - Matches Phase 2 of identification
            cmd = [
                "ffmpeg", "-y", "-ss", str(start_sec + offset), "-t", str(duration), "-i", str(audio_path),
                "-vn", "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
                "-f", "wav", "-loglevel", "error", str(tmp_wav)
            ]
            
            try:
                subprocess.run(cmd, check=True)
                
                # Load the filtered wav
                sr_in, data_in = wav.read(str(tmp_wav))
                y_slice = data_in.astype(np.float32) / 32768.0
                
                fp = compute_fingerprint(y_slice, sr_in)
                fingerprints.append(fp)
                time.sleep(0.01) # Small sleep to avoid same-second filename collision if running fast
            except Exception as e:
                print(f"    Failed to process window: {e}")
            finally:
                if tmp_wav.exists(): tmp_wav.unlink()
        
        if fingerprints:
            added, skipped = manager.add_song(name, fingerprints)
            learned_count += 1
            print(f"  Result: Added {added} new signatures, Skipped {skipped} duplicates for '{name}'")

    print(f"\nSUCCESS: Learned {learned_count} songs from {video_id}")

    # Clean up audio file if we learned something
    if learned_count > 0 and audio_path and audio_path.exists():
        try:
            audio_path.unlink()
            print(f"CLEANUP: Deleted audio file {audio_path.name}")
        except Exception as e:
            print(f"Error deleting audio file: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python learn_songs.py <VIDEO_ID>")
    else:
        learn_songs(sys.argv[1])
