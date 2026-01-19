import asyncio
import sys
import os
import json
import re
import time
import subprocess
import math
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import threading
import logging

# Configure logging for Shazamio
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
shazam_logger = logging.getLogger("shazamio")
shazam_logger.setLevel(logging.DEBUG)
request_logger = logging.getLogger("shazamio.request")
request_logger.setLevel(logging.DEBUG)

# Force UTF-8 for Windows Console
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Use local library version
sys.path.insert(0, "./shazamio_lib")
from shazamio import Shazam

# --- Configuration ---
START_DURATION = 15
STEP = 4
MAX_ATTEMPTS = 12
PORT = 5000

def get_optimal_sliding_windows(gap_size):
    """
    Calculates a list of (start_offset, duration) tuples for sliding windows.
    Matches the logic defined in the specification.
    """
    if gap_size <= 12:
        return [(0.0, gap_size)]
    
    # Calculate N (Number of tries)
    # N = clamp(ceil(GapSize / 10), 2, 10)
    n = max(2, min(10, math.ceil(gap_size / 10)))
    
    # Calculate S (Step Size)
    # Step = (GapSize - 12) / (N - 1)
    step = (gap_size - 12) / (n - 1)
    
    windows = []
    for i in range(n):
        start_offset = i * step
        duration = 12.0
        windows.append((round(start_offset, 3), round(duration, 3)))
    
    return windows

MARK_QUEUE = asyncio.Queue()
VIDEO_ID = "default"

def get_video_id():
    return sys.argv[1] if len(sys.argv) > 1 else "default"

def parse_ts(ts):
    try:
        if ':' in str(ts):
            parts = list(map(float, ts.split(':')))
            if len(parts) == 2: return parts[0] * 60 + parts[1]
            elif len(parts) == 3: return parts[0] * 3600 + parts[1] * 60 + parts[2]
        return float(ts)
    except: return 0.0

def format_timestamp_for_youtube(total_seconds):
    m, s = divmod(int(round(float(total_seconds))), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"

def format_song_entry(song_info):
    if not song_info: return ""
    
    # Custom Mappings (Expandable)
    # Format: "original name": "replacement name"
    mappings = {
        "nightcord - deaya": "キャットラビング - 25時、ナイトコードで。",
        "deaya - nightcord": "キャットラビング - 25時、ナイトコードで。"
    }

    # Check for exact or normalized match
    normalized = song_info.strip().lower()
    if normalized in mappings:
        return mappings[normalized]

    if ' - ' in song_info:
        parts = song_info.split(' - ', 1)
        # parts[0] is title, parts[1] is artist
        title = re.sub(r'\s*(\([^)]*\)|\[[^\]]*\])$', '', parts[0].strip())
        artist = parts[1].strip().replace('.', '')
        
        # If artist name is absurdly long (e.g. huge cast lists), keep only title
        if len(artist) > 60:
            return title
            
        return f"{title} - {artist}"
    return song_info.strip().replace('.', '')

def ensure_audio(video_id, video_dir):
    # Get true duration from YouTube first to validate existing/new files
    true_duration = 0
    try:
        duration_cmd = ["yt-dlp", "--get-duration", f"https://www.youtube.com/watch?v={video_id}"]
        dur_str = subprocess.check_output(duration_cmd).decode('utf-8').strip()
        # Handle formats like 1:20:30 or 5:10
        parts = list(map(int, dur_str.split(':')))
        if len(parts) == 3: true_duration = parts[0]*3600 + parts[1]*60 + parts[2]
        elif len(parts) == 2: true_duration = parts[0]*60 + parts[1]
        else: true_duration = parts[0]
    except:
        print("[DL] Warning: Could not fetch true duration from YouTube for validation.")

    # Check for existing audio in the video directory
    for ext in ['m4a', 'mp3', 'webm', 'mp4']:
        path = video_dir / f"audio.{ext}"
        if path.exists():
            # Validate existing file against YouTube duration
            try:
                probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
                local_dur = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
                
                # If local file is more than 5 seconds shorter than YT, it's truncated
                if true_duration > 0 and local_dur < (true_duration - 5):
                    print(f"[INFO] Existing file {path.name} is truncated ({int(local_dur)}s / {int(true_duration)}s). Deleting.")
                    path.unlink()
                    continue
            except: pass
            
            if path.exists():
                print(f"[INFO] Using existing audio: {path.name}")
                return path
    
    # Check root for backward compatibility
    for ext in ['m4a', 'mp3', 'webm', 'mp4']:
        old_path = Path(f"full_audio_{video_id}.{ext}")
        if old_path.exists():
            new_path = video_dir / f"audio.{ext}"
            old_path.rename(new_path)
            print(f"[INFO] Moved and using: {new_path.name}")
            return new_path

    path = video_dir / "audio.m4a"
    print(f"\n[DL] Starting download for {video_id}...")
    
    # Non-browser dependent commands (Bypasses the need for cookies/PO-Tokens)
    base_cmd = [
        "yt-dlp", 
        "-f", "ba/b",
        "-x", "--audio-format", "m4a",
        "--no-check-certificates",
        "--extractor-args", "youtube:player-client=android,ios;player-skip=webpage,configs",
        "-o", str(video_dir / "audio.%(ext)s"), 
        f"https://www.youtube.com/watch?v={video_id}"
    ]

    for attempt in range(3):
        try:
            cmd = base_cmd.copy()
            if attempt == 1:
                print(f"[DL] Retry 1: Trying m3u8 (HLS) formats...")
                # HLS streams often bypass the token/SABR restrictions
                cmd = [
                    "yt-dlp", "-f", "bestaudio[protocol=m3u8_native]/bestaudio", "-x", "--audio-format", "m4a",
                    "-o", str(video_dir / "audio.%(ext)s"),
                    f"https://www.youtube.com/watch?v={video_id}"
                ]
            elif attempt == 2:
                print(f"[DL] Retry 2: Trying basic web client fallback...")
                cmd = [
                    "yt-dlp", "-f", "ba/b", "-x", "--audio-format", "m4a",
                    "--extractor-args", "youtube:player-client=web;player-skip=webpage",
                    "-o", str(video_dir / "audio.%(ext)s"),
                    f"https://www.youtube.com/watch?v={video_id}"
                ]
            
            subprocess.run(cmd, check=True)
            
            # Validation: Check if file exists and has reasonable size/duration
            if path.exists():
                try:
                    probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
                    local_dur = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
                    
                    if true_duration > 0 and local_dur < (true_duration - 5):
                        print(f"[DL] WARNING: Downloaded file is truncated ({int(local_dur)}s / {int(true_duration)}s).")
                        path.unlink()
                        continue
                except Exception as probe_err:
                    print(f"[DL] Probe failed: {probe_err}")
                    pass
                
                print(f"[DL] Extraction complete and validated.")
                return path
        except Exception as e:
            print(f"[DL] Attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(2)
    
    return None

class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): return
    def do_OPTIONS(self):
        self.send_response(200); self.send_header('Access-Control-Allow-Origin', '*'); self.send_header('Access-Control-Allow-Headers', 'Content-Type'); self.end_headers()
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        if '/add_mark' in self.path:
            ts = query.get('ts', ['0'])[0]
            MARK_QUEUE.put_nowait(ts)
            self.send_response(200); self.send_header('Access-Control-Allow-Origin', '*'); self.end_headers(); self.wfile.write(b'{"status":"queued"}')

def start_server():
    HTTPServer(('localhost', PORT), BridgeHandler).serve_forever()

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
            "-af", "highpass=f=100,lowpass=f=8000,loudnorm=I=-16:TP=-1.5:LRA=11",
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
                print(f"[MATCH] {found_name}")
                break
            else:
                print(f"  [NO MATCH] Window {offset}s - {offset+d}s")
        except Exception as e:
            print(f"  [ERROR] Window processing failed: {e}")
        finally:
            if temp_name.exists(): temp_name.unlink()
        if found_name: break
    
    return found_name if found_name else "Unidentified"

async def main():

    global VIDEO_ID

    VIDEO_ID = get_video_id()

    # 1. Setup Directory Structure
    video_dir = Path.cwd() / "runs" / VIDEO_ID
    video_dir.mkdir(parents=True, exist_ok=True)

    progress_file = video_dir / "progress.json"
    youtube_out = video_dir / "results.txt"
    snippets_dir = video_dir / "snippets"
    if not snippets_dir.exists(): snippets_dir.mkdir()

    # Backward compatibility: Move files from root to runs folder
    old_progress = Path.cwd() / f"progress_{VIDEO_ID}.json"
    if old_progress.exists() and not progress_file.exists():
        old_progress.rename(progress_file)
    
    old_txt = Path.cwd() / f"youtube_comments_{VIDEO_ID}.txt"
    if old_txt.exists() and not youtube_out.exists():
        old_txt.rename(youtube_out)

    # 2. Start Server IMMEDIATELY so browser can mark while we download
    threading.Thread(target=start_server, daemon=True).start()
    print(f"[START] Video ID: {VIDEO_ID}")
    print(f"[INFO] Files stored in: {video_dir}")
    print(f"[INFO] Server listening on port {PORT}. YOU CAN START MARKING NOW.")

    results = {}
    insertion_order = []

    if progress_file.exists():
        with progress_file.open("r", encoding="utf-8") as f:
            raw_results = json.load(f)
        # Normalize keys to h:m:s format on load
        results = {format_timestamp_for_youtube(parse_ts(k)): v for k, v in raw_results.items()}
        # Restore insertion order from saved results, assuming chronological for existing files
        insertion_order = sorted(results.keys(), key=parse_ts)
        for m in results:
            if results[m] in ["", "Unidentified"]: results[m] = "Processing..."

    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    
    # 3. Download audio
    audio_path = ensure_audio(VIDEO_ID, video_dir)
    if not audio_path:
        print("[ERROR] Could not obtain audio file. Exiting.")
        return

    is_finished = False

    while True:
        queue_processed = False
        while not MARK_QUEUE.empty():
            ts = await MARK_QUEUE.get()
            queue_processed = True
            if ts == "[FINISH]": is_finished = True; continue
            if ts == "[UNDO]":
                if insertion_order:
                    last_added = insertion_order.pop()
                    if last_added in results:
                        del results[last_added]
                continue
            
            ts_formatted = format_timestamp_for_youtube(ts)
            if ts_formatted not in results:
                results[ts_formatted] = "Processing..."
                insertion_order.append(ts_formatted)
        
        if queue_processed:
            # Save state immediately after queue actions (Mark/Undo)
            with progress_file.open("w", encoding="utf-8") as f: 
                json.dump(results, f, ensure_ascii=False, indent=2)
            with youtube_out.open("w", encoding="utf-8", newline='') as f:
                current_keys = sorted(results.keys(), key=parse_ts)
                for m in current_keys:
                    f.write(f"{m} {format_song_entry(results[m])}\n")

        sorted_keys = sorted(results.keys(), key=parse_ts)
        target = None
        
        # Logic: Process "Processing..." markers ONLY (prevent infinite retries of failed/empty ones)
        for m in sorted_keys:
            if results[m] == "Processing...":
                is_most_recent = (insertion_order and m == insertion_order[-1])
                if not is_most_recent or is_finished:
                    target = m; break
        
        if target:
            idx = sorted_keys.index(target)
            current_sec = parse_ts(target)
            
            # Get video duration for the last marker gap calculation
            video_duration = 0
            try:
                probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
                video_duration = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
            except: pass

            gap = (parse_ts(sorted_keys[idx + 1]) - current_sec) if idx + 1 < len(sorted_keys) else (video_duration - current_sec if video_duration > current_sec else 120.0)
            print(f"\n[TARGET] {target} (Gap: {gap:.1f}s)")
            
            found_name = await identify_song(shazam, audio_path, current_sec, gap, snippets_dir)

            # Verify the target hasn't been UNDONE during processing
            if target in results:
                # If we found a name, save it. 
                # If we tried all durations and found nothing (or errored), save as "Unidentified" to stop retries
                results[target] = found_name if found_name and found_name != "Unidentified" else "Unidentified"
                with progress_file.open("w", encoding="utf-8") as f: json.dump(results, f, ensure_ascii=False, indent=2)
                with youtube_out.open("w", encoding="utf-8", newline='') as f:
                    current_keys = sorted(results.keys(), key=parse_ts)
                    for m in current_keys:
                        f.write(f"{m} {format_song_entry(results[m])}\n")
            else:
                print(f"[DISCARD] {target} was undone during processing.")
        elif is_finished and not any(res == "Processing..." for res in results.values()):
            print("\n[COMPLETE]")
            
            # Identify failed marks and export full durations
            print("[INFO] Exporting full durations for unidentified marks...")
            unidentified_dir = video_dir / "unidentified"
            unidentified_dir.mkdir(exist_ok=True)
            
            # Get video duration
            video_duration = 0
            try:
                probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
                video_duration = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
            except: pass

            failed_count = 0
            sorted_keys = sorted(results.keys(), key=parse_ts)
            for i, m in enumerate(sorted_keys):
                info = results[m]
                if not info or info == "Unidentified":
                    failed_count += 1
                    current_sec = parse_ts(m)
                    next_sec = parse_ts(sorted_keys[i+1]) if i+1 < len(sorted_keys) else video_duration
                    duration = max(0, next_sec - current_sec)
                    
                    # Use a clean filename and same extension as source
                    safe_m = m.replace(':', '-')
                    snippet_path = unidentified_dir / f"unidentified_{safe_m}{audio_path.suffix}"
                    
                    # Export full duration using stream copy (fast & high quality)
                    cmd = ["ffmpeg", "-y", "-ss", str(current_sec), "-t", str(duration), "-i", str(audio_path),
                           "-vn", "-c:a", "copy", str(snippet_path), "-loglevel", "quiet"]
                    try:
                        subprocess.run(cmd, check=True)
                        print(f"[EXPORT] Saved unidentified part: {snippet_path.name} ({int(duration)}s)")
                    except Exception as e:
                        print(f"[ERROR] Failed to export part for {m}: {e}")

            if failed_count > 0:
                print(f"[INFO] Exported {failed_count} full-length parts to: {unidentified_dir}")
            
            break
        else: await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())