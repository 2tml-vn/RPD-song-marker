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
import numpy as np
import scipy.io.wavfile as wav

# Configure logging for Shazamio
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
shazam_logger = logging.getLogger("shazamio")
shazam_logger.setLevel(logging.WARNING)
request_logger = logging.getLogger("shazamio.request")
request_logger.setLevel(logging.WARNING)

# Muffle internal decoder and network logs
logging.getLogger("shazamio_core").setLevel(logging.WARNING)
logging.getLogger("aiohttp.client").setLevel(logging.WARNING)
logging.getLogger("symphonia_core").setLevel(logging.WARNING)
logging.getLogger("symphonia_bundle_mp3").setLevel(logging.WARNING)

# Force UTF-8 for Windows Console with line buffering for immediate output
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

# Main script logger
logger = logging.getLogger("JRPD")
logger.setLevel(logging.DEBUG)

# Use installed library version
from shazamio import Shazam, Serialize
import shared_utils
from dna_matcher import DNAMatcher
from audio_features import extract_features

# --- Configuration ---
WINDOW_DURATION = shared_utils.WINDOW_DURATION
PORT = 5000

# Initialize Local Memory Matcher
dna_matcher = DNAMatcher()

# Custom Japanese to English Name Mappings
JAPANESE_TO_ENGLISH_MAP = {
    "金曜日のおはよう": "Kinyoubi no Ohayou",
    "君色に染まる": "kimiiro ni somaru",
    "夏色えがおで1,2,Jump!": "Natsuiro Egao de 1,2,Jump!",
    "サインはB": "Sign wa B",
    "青空Jumping Heart": "Aozora Jumping Heart",
    "おジャ魔女カーニバル!!": "Ojamajo Carnival!!",
    "えれくとりっく・えんじぇぅ": "Electric Angel",
    "輝夜の城で踊りたい": "Kaguya no Shiro de Odoritai",
    "虹色Passions!": "Nijiiro Passions!",
    "僕らは今のなかで": "Bokura wa Ima no Naka de",
    "アイドル活動!": "Idol Activity!",
    "OIDEMASE!!〜極楽〜": "OIDEMASE!!〜gokuraku〜" 
}


MARK_QUEUE = asyncio.Queue()
VIDEO_ID = "default"

def get_video_id():
    return sys.argv[1] if len(sys.argv) > 1 else "default"

def format_timestamp_for_youtube(total_seconds):
    m, s = divmod(int(round(float(total_seconds))), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"

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
            except:
                pass
            
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
    # Note: Using bestaudio/best to get high bitrate (Opus/AAC)
    base_cmd = [
        "yt-dlp", 
        "-f", "bestaudio/best",
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
            logger.info(f"[MARKER] Received: {ts}")
            MARK_QUEUE.put_nowait(ts)
            self.send_response(200); self.send_header('Access-Control-Allow-Origin', '*'); self.end_headers(); self.wfile.write(b'{"status":"queued"}')

def start_server():
    HTTPServer(('localhost', PORT), BridgeHandler).serve_forever()

async def identify_song(shazam, shazam_en, audio_path, current_sec, gap, snippets_dir):
    """
    Attempts to identify a song using temporary files.
    Phase 1: Try Shazam for all windows.
    Phase 2: If Shazam fails, try Local Memory for all windows.
    """
    sliding_windows = shared_utils.get_optimal_sliding_windows(gap)

    # --- Phase 1: Shazam ---
    logger.debug(f"Starting Phase 1: Shazam Identification ({len(sliding_windows)} windows)")
    for offset, d in sliding_windows:
        logger.debug(f"  Shazam Attempt {sliding_windows.index((offset, d)) + 1}/{len(sliding_windows)}: offset +{offset}s...")
        
        temp_name = snippets_dir / f"seg_{int(time.time())}_shazam.wav"
        cmd = [
            "ffmpeg", "-y", "-ss", str(current_sec + offset), "-t", str(d), "-i", str(audio_path),
            "-vn", "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
            "-f", "wav", "-loglevel", "error", str(temp_name)
        ]
        
        try:
            subprocess.run(cmd, check=True)
            if not temp_name.exists() or temp_name.stat().st_size < 1000:
                continue

            async def recognize_with_retry(client, file_path):
                try:
                    return await asyncio.wait_for(client.recognize(file_path), timeout=15)
                except:
                    return None

            out = await recognize_with_retry(shazam, str(temp_name))
            if not (out and 'track' in out):
                out = await recognize_with_retry(shazam_en, str(temp_name))

            if out and 'track' in out:
                track = out['track']
                original_title = track['title']
                artist = track['subtitle']
                track_id = track.get('key')

                if artist.lower() in ["moonbooter", "generic artist"]:
                    logger.debug(f"  Discarding false positive: {original_title} - {artist}")
                else:
                    title = shared_utils.clean_title(original_title)
                    en_name = None

                    if track_id:
                        try:
                            en_data = await shazam_en.track_about(int(track_id))
                            en_track = Serialize.track(data=en_data)
                            if en_track.title:
                                cleaned_shazam_en = shared_utils.clean_title(en_track.title)
                                # Only keep en_name if it's actually different from the Japanese title
                                if cleaned_shazam_en.lower() != title.lower():
                                    en_name = cleaned_shazam_en
                        except: pass

                    if title in JAPANESE_TO_ENGLISH_MAP:
                        en_name = JAPANESE_TO_ENGLISH_MAP[title]

                    # Only append en_name if it's not already contained in the title
                    if en_name and en_name.lower() not in title.lower():
                        title = f"{title} ({en_name})"

                    found_name = f"{title} - {artist}"
                    logger.info(f"  [MATCH] {found_name}")
                    return found_name

        except Exception as e:
            logger.error(f"  Shazam window failed: {e}")
        finally:
            if temp_name.exists(): temp_name.unlink()

    # --- Phase 2: Local Memory ---
    logger.debug("Starting Phase 2: Local Memory Fallback (High-Density Consensus Scan)")
    local_windows = shared_utils.get_local_matching_windows(gap)
    
    votes = {} # name -> [scores]
    
    for offset, d in local_windows:
        logger.debug(f"  Local Attempt {local_windows.index((offset, d)) + 1}/{len(local_windows)}: offset +{offset}s...")
        
        temp_name = snippets_dir / f"seg_{int(time.time())}_local.wav"
        cmd = [
            "ffmpeg", "-y", "-ss", str(current_sec + offset), "-t", str(d), "-i", str(audio_path),
            "-vn", "-ar", "22050", "-ac", "1", "-acodec", "pcm_s16le",
            "-f", "wav", "-loglevel", "error", str(temp_name)
        ]
        
        try:
            subprocess.run(cmd, check=True)
            if not temp_name.exists() or temp_name.stat().st_size < 1000:
                continue

            sr_in, data_in = wav.read(str(temp_name))
            y_in = data_in.astype(np.float32) / 32768.0
            fp_in = extract_features(y_in, sr_in)
            
            # Use lower threshold 0.85 for "voting" but we'll be stricter in the end
            hit_name, hit_score, top = dna_matcher.find_match(fp_in, threshold=0.85)
            
            if hit_name:
                if hit_name not in votes: votes[hit_name] = []
                votes[hit_name].append(hit_score)
                logger.debug(f"    Window +{offset}s: Voted for '{hit_name}' ({hit_score:.3f})")
            elif top:
                logger.debug(f"    Window +{offset}s: No high match. Top candidate: {top[0][0]} ({top[0][1]:.3f})")

        except Exception as local_err:
            logger.debug(f"    Local window failed: {local_err}")
        finally:
            if temp_name.exists(): temp_name.unlink()
            
    # --- Election Results ---
    if not votes:
        return "Unidentified"
        
    # Sort candidates by number of votes, then by average score
    candidates = []
    for name, scores in votes.items():
        avg_score = sum(scores) / len(scores)
        candidates.append({
            "name": name,
            "votes": len(scores),
            "avg": avg_score,
            "max": max(scores)
        })
    
    candidates.sort(key=lambda x: (x["votes"], x["avg"]), reverse=True)
    winner = candidates[0]
    
    logger.debug(f"Election Results: {len(candidates)} candidates found.")
    for c in candidates[:3]:
        logger.debug(f"  - {c['name']}: {c['votes']} votes, Avg Similarity {c['avg']:.3f}")

    # DECISION LOGIC:
    # 1. Clear Winner: At least 2 votes AND avg similarity >= 0.9
    if winner["votes"] >= 2 and winner["avg"] >= 0.9:
        logger.info(f"  [LOCAL MATCH] {winner['name']} (Consensus: {winner['votes']} windows agreed, Avg {winner['avg']:.3f})")
        return winner["name"]
    
    # 2. Strong Single: Only 1 vote but very high similarity (> 0.96)
    if winner["votes"] == 1 and winner["max"] >= 0.96:
        logger.info(f"  [LOCAL MATCH] {winner['name']} (High Single Match: {winner['max']:.3f})")
        return winner["name"]

    logger.info(f"  [DISCARD] No consensus reached. Winner '{winner['name']}' had {winner['votes']} votes but failed safety checks.")
    return "Unidentified"

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
    logger.info(f"[START] Video ID: {VIDEO_ID}")
    logger.info(f"Files stored in: {video_dir}")
    logger.info(f"Server listening on port {PORT}. YOU CAN START MARKING NOW.")

    results = {}
    insertion_order = []
    marker_arrival_times = {} # Track when we first saw a marker for Undo protection

    if progress_file.exists():
        with progress_file.open("r", encoding="utf-8") as f:
            raw_results = json.load(f)
        # Normalize keys to h:m:s format on load
        results = {format_timestamp_for_youtube(shared_utils.parse_ts(k)): v for k, v in raw_results.items()}
        # Restore insertion order from saved results, assuming chronological for existing files
        insertion_order = sorted(results.keys(), key=shared_utils.parse_ts)
        for m in results:
            if results[m] == "":
                results[m] = "Processing..."
            else:
                # Apply filter to existing entries but keep them if already identified/failed
                results[m] = shared_utils.format_song_entry(results[m])
            # For loaded files, we assume they are "old enough" to process immediately
            marker_arrival_times[m] = 0 

    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    shazam_en = Shazam(language='en-US', endpoint_country='US')

    # 3. Download audio
    audio_path = ensure_audio(VIDEO_ID, video_dir)
    if not audio_path:
        logger.error("Could not obtain audio file. Exiting.")
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
                        if last_added in marker_arrival_times: del marker_arrival_times[last_added]
                continue
            
            ts_formatted = format_timestamp_for_youtube(ts)
            if ts_formatted not in results:
                results[ts_formatted] = "Processing..."
                insertion_order.append(ts_formatted)
                marker_arrival_times[ts_formatted] = time.time()
        
        if queue_processed:
            # Save state immediately after queue actions (Mark/Undo)
            with progress_file.open("w", encoding="utf-8") as f: 
                json.dump(results, f, ensure_ascii=False, indent=2)
            with youtube_out.open("w", encoding="utf-8", newline='') as f:
                current_keys = sorted(results.keys(), key=shared_utils.parse_ts)
                for m in current_keys:
                    f.write(f"{m} {shared_utils.format_song_entry(results[m])}\n")

        sorted_keys = sorted(results.keys(), key=shared_utils.parse_ts)
        target = None
        
        # Logic: Process "Processing..." markers ONLY if the NEXT marker is 10s old (Undo protection)
        for i, m in enumerate(sorted_keys):
            if results[m] == "Processing...":
                # Check if we have a next marker to define the gap
                if i + 1 < len(sorted_keys):
                    next_m = sorted_keys[i+1]
                    # Only process if the marker that ENDS this gap has existed for 10 seconds
                    # This gives the user time to UNDO that next marker if it was a mistake.
                    if is_finished or (time.time() - marker_arrival_times.get(next_m, 0) > 10):
                        target = m; break
                else:
                    # It's the last marker. We only process it if FINISH was pressed.
                    if is_finished:
                        target = m; break
        
        if target:
            idx = sorted_keys.index(target)
            current_sec = shared_utils.parse_ts(target)
            
            # Get video duration for the last marker gap calculation
            video_duration = 0
            try:
                probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
                video_duration = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
            except:
                pass

            gap = (shared_utils.parse_ts(sorted_keys[idx + 1]) - current_sec) if idx + 1 < len(sorted_keys) else (video_duration - current_sec if video_duration > current_sec else 120.0)
            logger.info(f"[TARGET] {target} (Gap: {gap:.1f}s)")
            
            found_name = await identify_song(shazam, shazam_en, audio_path, current_sec, gap, snippets_dir)

            # Verify the target hasn't been UNDONE during processing
            if target in results:
                # Format before saving to results so JSON is also clean
                cleaned_name = shared_utils.format_song_entry(found_name) if found_name and found_name != "Unidentified" else "Unidentified"
                results[target] = cleaned_name
                
                with progress_file.open("w", encoding="utf-8") as f: 
                    json.dump(results, f, ensure_ascii=False, indent=2)
                with youtube_out.open("w", encoding="utf-8", newline='') as f:
                    current_keys = sorted(results.keys(), key=shared_utils.parse_ts)
                    for m in current_keys:
                        f.write(f"{m} {results[m]}\n")
            else:
                logger.warning(f"[DISCARD] {target} was undone during processing.")
        elif is_finished and not any(res == "Processing..." for res in results.values()):
            logger.info("[COMPLETE]")
            
            # Export unidentified.json
            unidentified_data = {}
            sorted_keys = sorted(results.keys(), key=shared_utils.parse_ts)
            for i, m in enumerate(sorted_keys):
                if results[m] == "Unidentified":
                    next_m = sorted_keys[i+1] if i+1 < len(sorted_keys) else "END"
                    unidentified_data[m] = {
                        "end": next_m,
                        "name": ""
                    }
            
            if unidentified_data:
                unidentified_file = video_dir / "unidentified.json"
                with unidentified_file.open("w", encoding="utf-8") as f:
                    json.dump(unidentified_data, f, ensure_ascii=False, indent=2)
                logger.info(f"[EXPORT] Created {unidentified_file.name}")
                logger.info(f"[INFO] Audio file preserved for learning: {audio_path.name}")
            else:
                # Clean up audio file ONLY if everything was identified
                if audio_path and audio_path.exists():
                    try:
                        audio_path.unlink()
                        logger.info(f"[CLEANUP] Deleted audio file: {audio_path.name}")
                    except Exception as e:
                        logger.error(f"Failed to delete audio file: {e}")
            
            break
        else: await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
