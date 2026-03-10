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

# Muffle internal decoder and network logs
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
import acrcloud

# --- Configuration ---
WINDOW_DURATION = shared_utils.WINDOW_DURATION
PORT = 5000

# ACRCloud Config
ACR_CONFIG = {
    'host': 'identify-ap-southeast-1.acrcloud.com',
    'access_key': '9f6854a4b6a69192b2d22a3e6d64ebf9',
    'access_secret': 'GYUh0PMKeUVqLHXT26mTNrepehI9FIE3KHZ0kZFD',
}

MARK_QUEUE = asyncio.Queue()
SELECTION_QUEUE = asyncio.Queue()
MAIN_LOOP = None
CURRENT_SEEK_TS = -1
CLEANUP_CANDIDATES = []
RESULTS = {}
IS_FINISHED = False
IS_SESSION_DONE = False

SHAZAM_REMAP = {
    "nightcord - deaya": "キャットラビング (Cat Loving)",
    "Chika Dance - Gudrap": "チカっとチカ千花っ♡ (Chikatto Chika Chika♡)",
    "Lucky Star Opening - AnimeHub": "もってけ！セーラーふく (Motteke! Sailor Fuku)",
    "踊 (Odo) - Vivid BAD SQUAD": "踊 (Odo) - Ado",
}
# --- Song Name Overrides (loaded from JSON) ---
SONG_OVERRIDES_FILE = Path(__file__).parent / "song_name_overrides.json"
SONG_OVERRIDES = {}

# Display format template — customize how song names appear in output.
# Variables: {ori_song}, {int_song}, {ori_artist}, {int_artist}
# Sections in [...] are optional: only included if all variables inside have values.

DISPLAY_FORMAT = "{ori_artist} - {ori_song} [ ({int_song})]"
# User-defined phrase replacements: if song name contains the phrase, replace with the set song name
# Format: ("phrase to find", "replacement song name")
USER_PHRASE_REPLACE = [
    ("LOST IN PARADISE", "LOST IN PARADISE (Jujutsu Kaisen Ending Theme Song) [feat. AKLO] - ALI"),
    ("STAR☆T☆RAIN", "STAR☆T☆RAIN"),
    ("Umapyoi Legend", "うまぴょい伝説 (Umapyoi Densetsu) - ウマ娘 プリティーダービー"),
    ("Ensemble Taiso!!", "あんさんぶる体操！！ (Ensemble Taisou!!)"),
    ("MIRACLE WAVE", "MIRACLE WAVE - Aqours",)
]

def load_song_overrides():
    """Load song name overrides from JSON file."""
    global SONG_OVERRIDES
    if SONG_OVERRIDES_FILE.exists():
        with open(SONG_OVERRIDES_FILE, "r", encoding="utf-8") as f:
            SONG_OVERRIDES = json.load(f)
    logger.info(f"[OVERRIDES] Loaded {len(SONG_OVERRIDES)} entries from {SONG_OVERRIDES_FILE.name}")

def save_song_overrides():
    """Save song name overrides to JSON file (sorted alphabetically by key)."""
    sorted_overrides = dict(sorted(SONG_OVERRIDES.items(), key=lambda x: x[0].lower()))
    with open(SONG_OVERRIDES_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted_overrides, f, ensure_ascii=False, indent=2)

def lookup_song_override(title):
    """
    Exact-match lookup by original name (key) or intl name.
    Returns (orig_key, data_dict) or (None, None).
    """
    if title in SONG_OVERRIDES:
        return title, SONG_OVERRIDES[title]
    for orig_name, data in SONG_OVERRIDES.items():
        intl = data.get('intl', '')
        if intl and intl == title:
            return orig_name, data
    return None, None

def format_display_name(ori_song, int_song=None, ori_artist=None, int_artist=None):
    """
    Format song name using DISPLAY_FORMAT template.
    Sections in [...] are optional: only included if all {variables} inside have values.
    """
    variables = {
        'ori_song': ori_song or '',
        'int_song': int_song or '',
        'ori_artist': ori_artist or '',
        'int_artist': int_artist or '',
    }
    def replace_optional(match):
        section = match.group(1)
        vars_in_section = re.findall(r'\{(\w+)\}', section)
        for var_name in vars_in_section:
            if not variables.get(var_name):
                return ''
        for var_name, val in variables.items():
            section = section.replace('{' + var_name + '}', val)
        return section
    result = re.sub(r'\[([^\]]*)\]', replace_optional, DISPLAY_FORMAT)
    for var_name, val in variables.items():
        result = result.replace('{' + var_name + '}', val)
    # Collapse multiple consecutive spaces into one
    result = re.sub(r'  +', ' ', result)
    return result.strip()

def auto_register_song(ori_song, int_song=None, ori_artist=None, int_artist=None):
    """Auto-register a newly identified song in the overrides JSON (if not already present)."""
    if not ori_song:
        return
    # Check if already registered (by ori or intl key)
    existing_key, _ = lookup_song_override(ori_song)
    if existing_key:
        return
    entry = {}
    if int_song: entry['intl'] = int_song
    if ori_artist: entry['artist_orig'] = ori_artist
    if int_artist: entry['artist_intl'] = int_artist
    SONG_OVERRIDES[ori_song] = entry
    save_song_overrides()
    logger.debug(f"[OVERRIDES] Auto-registered: {ori_song}")

async def resolve_song_name(title_clean, artist, track_id=None, shazam_en=None):
    """
    Resolve a detected song into a formatted display name using overrides and Shazam EN API.
    Also auto-registers new songs into the overrides JSON.
    Returns the formatted display name string.
    """
    title_clean = strip_extra_info(title_clean)

    # Look up in song overrides (exact match on original or intl name)
    orig_key, override_data = lookup_song_override(title_clean)

    if override_data:
        ori_song = orig_key

        # Resolve international song name
        if override_data.get('intl_override'):
            int_song = override_data.get('intl')
        else:
            # Try Shazam EN API first, fallback to stored intl
            int_song = None
            if track_id and shazam_en:
                try:
                    en_data = await shazam_en.track_about(int(track_id))
                    en_title = en_data['track'].get('title') if isinstance(en_data, dict) and 'track' in en_data else (en_data['title'] if isinstance(en_data, dict) and 'title' in en_data else getattr(en_data, 'title', None))
                    if en_title and en_title.lower() != ori_song.lower():
                        int_song = strip_extra_info(en_title)
                except: pass
            if not int_song:
                int_song = override_data.get('intl')
            # Skip if same as original
            if int_song and int_song.lower() == ori_song.lower():
                int_song = None

        # Resolve artist
        ori_artist = override_data.get('artist_orig') if override_data.get('artist_orig_override') else artist
        int_artist = override_data.get('artist_intl') if override_data.get('artist_intl_override') else None

        return format_display_name(ori_song, int_song, ori_artist, int_artist)
    else:
        # No override found — try Shazam EN API for translation
        en_name = None
        if track_id and shazam_en:
            try:
                en_data = await shazam_en.track_about(int(track_id))
                en_title = en_data['track'].get('title') if isinstance(en_data, dict) and 'track' in en_data else (en_data['title'] if isinstance(en_data, dict) and 'title' in en_data else getattr(en_data, 'title', None))
                if en_title and en_title.lower() != title_clean.lower():
                    en_name = strip_extra_info(en_title)
            except: pass

        ori_song = title_clean
        int_song = en_name if en_name and en_name.lower() != title_clean.lower() else None
        ori_artist = artist

        # Auto-register in overrides JSON
        auto_register_song(ori_song, int_song, ori_artist, None)

        return format_display_name(ori_song, int_song, ori_artist, None)

def apply_user_phrase_replace(full_name):
    """
    If the song name contains a user-specified phrase, replace it with a user-specified song name.
    Configured via USER_PHRASE_REPLACE list above.
    """
    if not full_name: return full_name
    for phrase, replacement in USER_PHRASE_REPLACE:
        if phrase.lower() in full_name.lower():
            return replacement
    return full_name


VIDEO_ID = "default"
ACR_ONLY = False
SKIP_RECOG = False

def parse_args():
    global VIDEO_ID, ACR_ONLY, SKIP_RECOG
    args = sys.argv[1:]
    
    if "acrcloud" in [a.lower() for a in args]:
        ACR_ONLY = True
        args = [a for a in args if a.lower() != "acrcloud"]
    
    if "skip" in [a.lower() for a in args]:
        SKIP_RECOG = True
        args = [a for a in args if a.lower() != "skip"]

    if args:
        VIDEO_ID = args[0]
    else:
        VIDEO_ID = "default"

def format_timestamp_for_youtube(total_seconds):
    m, s = divmod(int(round(float(total_seconds))), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"

def ensure_audio(video_id, video_dir):
    true_duration = 0
    try:
        duration_cmd = ["yt-dlp", "--get-duration", f"https://www.youtube.com/watch?v={video_id}"]
        dur_str = subprocess.check_output(duration_cmd).decode('utf-8').strip()
        parts = list(map(int, dur_str.split(':')))
        if len(parts) == 3: true_duration = parts[0]*3600 + parts[1]*60 + parts[2]
        elif len(parts) == 2: true_duration = parts[0]*60 + parts[1]
        else: true_duration = parts[0]
    except:
        print("[DL] Warning: Could not fetch true duration from YouTube for validation.")

    for ext in ['m4a', 'mp3', 'webm', 'mp4']:
        path = video_dir / f"audio.{ext}"
        if path.exists():
            try:
                probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
                local_dur = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
                if true_duration > 0 and local_dur < (true_duration - 5):
                    path.unlink()
                    continue
            except: pass
            if path.exists():
                print(f"[INFO] Using existing audio: {path.name}")
                return path

    path = video_dir / "audio.m4a"
    base_cmd = [
        "yt-dlp", "-f", "bestaudio/best", "-x", "--audio-format", "m4a",
        "--no-check-certificates",
        "--extractor-args", "youtube:player-client=android,ios;player-skip=webpage,configs",
        "-o", str(video_dir / "audio.%(ext)s"), f"https://www.youtube.com/watch?v={video_id}"
    ]

    for attempt in range(3):
        try:
            cmd = base_cmd.copy()
            if attempt == 1:
                cmd = ["yt-dlp", "-f", "bestaudio[protocol=m3u8_native]/bestaudio", "-x", "--audio-format", "m4a", "-o", str(video_dir / "audio.%(ext)s"), f"https://www.youtube.com/watch?v={video_id}"]
            elif attempt == 2:
                cmd = ["yt-dlp", "-f", "ba/b", "-x", "--audio-format", "m4a", "--extractor-args", "youtube:player-client=web;player-skip=webpage", "-o", str(video_dir / "audio.%(ext)s"), f"https://www.youtube.com/watch?v={video_id}"]
            subprocess.run(cmd, check=True)
            if path.exists():
                return path
        except: time.sleep(2)
    return None

class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args): return
    def do_OPTIONS(self):
        self.send_response(200); self.send_header('Access-Control-Allow-Origin', '*'); self.send_header('Access-Control-Allow-Headers', 'Content-Type'); self.end_headers()
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        if '/add_mark' in self.path:
            ts = query.get('ts', ['0'])[0]
            if MAIN_LOOP:
                MAIN_LOOP.call_soon_threadsafe(MARK_QUEUE.put_nowait, ts)
            self.send_response(200); self.send_header('Access-Control-Allow-Origin', '*'); self.end_headers(); self.wfile.write(b'{"status":"queued"}')
        elif '/status' in self.path:
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.end_headers()
            
            # Determine status message
            status_msg = ""
            if IS_SESSION_DONE:
                status_msg = "All identified! Finishing..."
            elif IS_FINISHED:
                processing_count = sum(1 for v in RESULTS.values() if v == "Processing...")
                if processing_count > 0:
                    status_msg = f"Still identifying {processing_count} songs..."
                else:
                    unidentified_count = sum(1 for v in RESULTS.values() if v == "Unidentified")
                    if unidentified_count > 0:
                        status_msg = f"Starting cleanup for {unidentified_count} gaps"
                    else:
                        status_msg = "All identified! Finishing..."

            response = json.dumps({
                "seek_ts": CURRENT_SEEK_TS, 
                "candidates": CLEANUP_CANDIDATES,
                "status_msg": status_msg,
                "marks": sorted(RESULTS.keys(), key=shared_utils.parse_ts) if IS_FINISHED else []
            })
            self.wfile.write(response.encode('utf-8'))
        elif '/select' in self.path:
            choice = query.get('choice', [None])[0]
            if choice and MAIN_LOOP:
                MAIN_LOOP.call_soon_threadsafe(SELECTION_QUEUE.put_nowait, choice)
            self.send_response(200); self.send_header('Access-Control-Allow-Origin', '*'); self.end_headers(); self.wfile.write(b'{"status":"ok"}')

def start_server():
    HTTPServer(('127.0.0.1', PORT), BridgeHandler).serve_forever()

def strip_extra_info(text):
    """
    Precisely removes tags like '(Instrumental)', '[Instrumental]', '(feat. ...)', '[feat.]', '(Ver...)', '(Edit...)', '(Vocal...)', '(mix)', and '(サイズ)'
    Handles nested parentheses/brackets (one level).
    """
    if not text: return text
    # 1. Remove (Instrumental)
    text = re.sub(r'\s*\([Ii]nstrumental\)', '', text)
    # 2. Remove (feat. ...)
    text = re.sub(r'\s*\([Ff]eat\.(?:[^()]|\([^()]*\))*\)', '', text)
    # 3. Remove anything in () that contains "ver", "edit", or "vocal" (case-insensitive)
    pattern_extra = r'\s*\((?=[^)]*?(?:[Vv][Ee][Rr]|[Ee][Dd][Ii][Tt]|[Vv][Oo][Cc][Aa][Ll]))(?:[^()]|\([^()]*\))*\)'
    text = re.sub(pattern_extra, '', text)
    # 4. Remove anything in () that contains "サイズ" (Japanese for "size", e.g., "(TVサイズ)")
    pattern_size = r'\s*\((?=[^)]*?サイズ)(?:[^()]|\([^()]*\))*\)'
    text = re.sub(pattern_size, '', text)
    # 5. Remove anything in () that contains "mix" (case-insensitive, e.g., "(Remix)", "(Extended Mix)")
    pattern_mix = r'\s*\((?=[^)]*?mix)(?:[^()]|\([^()]*\))*\)'
    text = re.sub(pattern_mix, '', text)
    # 6. Remove any square-bracket tag regardless of content (e.g., "[Remix]", "[feat. ...]", "[TV Size]")
    text = re.sub(r'\s*\[[^\]]*\]', '', text)
    return text

def strip_shared_tags(ja, en):
    """
    If both titles have the same (...) content, remove it from both before comparison.
    Handles nested parentheses.
    """
    if not ja or not en: return ja, en
    paren_pattern = r'\((?:[^()]|\([^()]*\))*\)'
    ja_tags = re.findall(paren_pattern, ja)
    en_tags = re.findall(paren_pattern, en)
    for tag_with_parens in ja_tags:
        if tag_with_parens in en_tags:
            safe_tag = re.escape(tag_with_parens)
            ja = re.sub(r'\s*' + safe_tag, '', ja)
            en = re.sub(r'\s*' + safe_tag, '', en)
    return ja, en

async def identify_song(shazam, shazam_en, audio_path, current_sec, gap, snippets_dir, is_last_segment=False):
    sliding_windows = shared_utils.get_optimal_sliding_windows(gap)
    if not ACR_ONLY:
        logger.debug(f"Starting Phase 1: Shazam Identification ({len(sliding_windows)} windows)")
        for i, (offset, d) in enumerate(sliding_windows):
            logger.debug(f"  [Shazam] Attempt {i+1}/{len(sliding_windows)}: Offset +{offset}s, Dur {d}s")
            temp_name = snippets_dir / f"seg_{int(time.time())}_shazam.wav"
            cmd = ["ffmpeg", "-y", "-ss", str(current_sec + offset), "-t", str(d), "-i", str(audio_path), "-vn", "-loglevel", "error", str(temp_name)]
            try:
                subprocess.run(cmd, check=True)
                if not temp_name.exists(): continue
                # 1. Try Shazam (JP Only for direct ID)
                async def recognize_shazam(client, file_path):
                    try: return await client.recognize(file_path)
                    except: return None
                
                out = await recognize_shazam(shazam, str(temp_name))
                
                if out and 'track' in out:
                    track = out['track']
                    logger.debug(f"  [RAW SHAZAM] {track['title']} - {track['subtitle']}")
                    title_clean = shared_utils.clean_title(track['title'])
                    artist = track['subtitle']
                    track_id = track.get('key')
                    full_match_name = await resolve_song_name(title_clean, artist, track_id, shazam_en)
                    if full_match_name in SHAZAM_REMAP: full_match_name = SHAZAM_REMAP[full_match_name]
                    full_match_name = apply_user_phrase_replace(full_match_name)
                    logger.info(f"  [MATCH - SHAZAM] {full_match_name}")
                    return full_match_name
            except Exception as e: logger.error(f"  [Shazam] Error: {e}")
            finally:
                if temp_name.exists(): 
                    try: temp_name.unlink()
                    except: pass
    else: logger.info("  [SKIP] Phase 1 (Shazam) skipped due to ACR_ONLY mode.")

    logger.debug(f"Starting Phase 2: ACRCloud Fallback ({len(sliding_windows)} windows)")
    for i, (offset, d) in enumerate(sliding_windows):
        logger.debug(f"  [ACRCloud] Attempt {i+1}/{len(sliding_windows)}: Offset +{offset}s, Dur {d}s")
        temp_name = snippets_dir / f"seg_{int(time.time())}_acr.wav"
        cmd = ["ffmpeg", "-y", "-ss", str(current_sec + offset), "-t", str(d), "-i", str(audio_path), "-vn", "-loglevel", "error", str(temp_name)]
        try:
            subprocess.run(cmd, check=True)
            if not temp_name.exists(): continue
            acr_match = await acrcloud.recognize(str(temp_name), access_key=ACR_CONFIG['access_key'], access_secret=ACR_CONFIG['access_secret'], host=ACR_CONFIG['host'])
            if acr_match:
                logger.debug(f"  [RAW ACRCLOUD] {acr_match}")
                if " - " in acr_match:
                    title, artist = acr_match.rsplit(" - ", 1)
                    title_clean = shared_utils.clean_title(title)
                    acr_match = await resolve_song_name(title_clean, artist, None, shazam_en)
                    if acr_match in SHAZAM_REMAP: acr_match = SHAZAM_REMAP[acr_match]
                    acr_match = apply_user_phrase_replace(acr_match)
                logger.info(f"  [MATCH - ACRCLOUD] {acr_match}")
                return acr_match
        except Exception as e: logger.error(f"  [ACRCloud] Error: {e}")
        finally:
            if temp_name.exists(): 
                try: temp_name.unlink()
                except: pass
    logger.info("  [FINAL RESULT] Unidentified"); return "Unidentified"

async def main():
    global VIDEO_ID, MAIN_LOOP, RESULTS, IS_FINISHED, IS_SESSION_DONE
    MAIN_LOOP = asyncio.get_running_loop()
    parse_args()
    load_song_overrides()
    video_dir = Path.cwd() / "runs" / VIDEO_ID
    video_dir.mkdir(parents=True, exist_ok=True)
    progress_file = video_dir / "progress.json"
    youtube_out = video_dir / "results.txt"
    snippets_dir = video_dir / "snippets"
    if not snippets_dir.exists(): snippets_dir.mkdir()

    threading.Thread(target=start_server, daemon=True).start()
    logger.info(f"[START] Video ID: {VIDEO_ID}")
    logger.info(f"Files stored in: {video_dir}")
    logger.info(f"Server listening on port {PORT}. YOU CAN START MARKING NOW.")

    insertion_order = []
    marker_arrival_times = {}

    if progress_file.exists():
        with progress_file.open("r", encoding="utf-8") as f: raw_results = json.load(f)
        RESULTS = {format_timestamp_for_youtube(shared_utils.parse_ts(k)): v for k, v in raw_results.items()}
        insertion_order = sorted(RESULTS.keys(), key=shared_utils.parse_ts)
        for m in RESULTS:
            marker_arrival_times[m] = 0
            if RESULTS[m] == "" or RESULTS[m] is None: RESULTS[m] = "Processing..."

    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    shazam_en = Shazam(language='en-US', endpoint_country='US')
    audio_path = ensure_audio(VIDEO_ID, video_dir)
    if not audio_path: return

    def save_state():
        with progress_file.open("w", encoding="utf-8") as f: json.dump(RESULTS, f, ensure_ascii=False, indent=2)
        with youtube_out.open("w", encoding="utf-8", newline='') as f:
            for m in sorted(RESULTS.keys(), key=shared_utils.parse_ts):
                val = shared_utils.format_song_entry(RESULTS[m])
                if val == "Unidentified": val = ""
                f.write(f"{m} {val}\n")

    if SKIP_RECOG:
        logger.info("[SKIP] Bypassing identification. Moving to cleanup.")
        for m in RESULTS:
            if RESULTS[m] == "Processing...": RESULTS[m] = "Unidentified"
        IS_FINISHED = True; save_state()

    async def queue_worker():
        global IS_FINISHED
        while True:
            ts = await MARK_QUEUE.get()
            try:
                if ts == "[FINISH]": IS_FINISHED = True; continue
                if ts == "[UNDO]":
                    if insertion_order:
                        last_added = insertion_order.pop()
                        logger.info(f"[UNDO] Removed: {last_added}")
                        if last_added in RESULTS: del RESULTS[last_added]
                    else: logger.warning("[UNDO] Requested but no markers to remove.")
                    save_state(); continue
                ts_formatted = format_timestamp_for_youtube(ts)
                logger.info(f"[MARKER] Received: {ts_formatted}")
                if ts_formatted not in RESULTS:
                    RESULTS[ts_formatted] = "Processing..."; insertion_order.append(ts_formatted);
                save_state()
            finally: MARK_QUEUE.task_done()

    worker_task = asyncio.create_task(queue_worker())

    while True:
        sorted_keys = sorted(RESULTS.keys(), key=shared_utils.parse_ts)
        target = None
        for i, m in enumerate(sorted_keys):
            if RESULTS[m] == "Processing...":
                if i + 2 < len(sorted_keys) or IS_FINISHED: target = m; break
        
        if target and not SKIP_RECOG:
            idx = sorted_keys.index(target)
            current_sec = shared_utils.parse_ts(target)
            video_duration = 0
            try:
                probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
                video_duration = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
            except: pass
            gap = (shared_utils.parse_ts(sorted_keys[idx + 1]) - current_sec) if idx + 1 < len(sorted_keys) else (video_duration - current_sec if video_duration > current_sec else 120.0)
            logger.info(f"[TARGET] {target} (Gap: {gap:.1f}s)")
            found_name = await identify_song(shazam, shazam_en, audio_path, current_sec, gap, snippets_dir, (idx + 1 == len(sorted_keys)))
            if target in RESULTS:
                RESULTS[target] = shared_utils.format_song_entry(found_name) if found_name != "Unidentified" else "Unidentified"
                save_state()
        elif IS_FINISHED and not any(res == "Processing..." for res in RESULTS.values()):
            worker_task.cancel()
            try: await worker_task
            except asyncio.CancelledError: pass

            missed_file = Path("list_of_missed_songs_by_shazam.txt")
            if missed_file.exists():
                with open(missed_file, "r", encoding="utf-8") as f: candidates = [line.strip() for line in f if line.strip()]
                unidentified_keys = [k for k in sorted(RESULTS.keys(), key=shared_utils.parse_ts) if RESULTS[k] == "Unidentified"]
                if candidates and unidentified_keys:
                    global CLEANUP_CANDIDATES, CURRENT_SEEK_TS
                    candidates.sort(key=lambda x: x.lower())
                    CLEANUP_CANDIDATES = candidates
                    video_duration = 0
                    try:
                        probe_cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)]
                        video_duration = float(subprocess.check_output(probe_cmd).decode('utf-8').strip())
                    except: pass

                    all_keys = sorted(RESULTS.keys(), key=shared_utils.parse_ts)
                    quit_cleanup = False
                    for k in unidentified_keys:
                        if quit_cleanup: break
                        idx = all_keys.index(k)
                        start_sec = shared_utils.parse_ts(k)
                        logger.info(f"[CLEANUP] Current Gap: {k}")
                        CURRENT_SEEK_TS = int(start_sec)
                        choice = await SELECTION_QUEUE.get()
                        if choice == 'q': quit_cleanup = True; break
                        if choice == 's': continue
                        try:
                            if str(choice).startswith('+'):
                                selected = str(choice)[1:].strip()
                                RESULTS[k] = selected
                                logger.info(f"✓ Manually Added: {selected}")
                                if selected not in candidates: candidates.append(selected)
                                candidates.sort(key=lambda x: x.lower()); CLEANUP_CANDIDATES = candidates
                                with open(missed_file, "w", encoding="utf-8") as f:
                                    for c in candidates: f.write(c + "\n")
                                save_state(); continue
                            val = int(choice)
                            if 0 <= val < len(candidates):
                                selected = candidates[val]; RESULTS[k] = selected; logger.info(f"✓ Assigned: {selected}"); save_state()
                        except: pass
                    CLEANUP_CANDIDATES = []; CURRENT_SEEK_TS = -1
            
            unidentified_data = {}
            sorted_keys = sorted(RESULTS.keys(), key=shared_utils.parse_ts)
            for i, m in enumerate(sorted_keys):
                if RESULTS[m] == "Unidentified":
                    next_m = sorted_keys[i+1] if i+1 < len(sorted_keys) else "END"
                    unidentified_data[m] = {"end": next_m, "name": ""}
            if unidentified_data:
                unidentified_file = video_dir / "unidentified.json"
                with unidentified_file.open("w", encoding="utf-8") as f: json.dump(unidentified_data, f, ensure_ascii=False, indent=2)
                logger.info(f"[EXPORT] Created {unidentified_file.name}")
            else:
                if audio_path and audio_path.exists():
                    try:
                        audio_path.unlink()
                        logger.info(f"[CLEANUP] Deleted audio file: {audio_path.name}")
                    except: pass
            
            # Open results.txt in Notepad++
            try:
                if youtube_out.exists():
                    npp_path = r'C:\Program Files\Notepad++\notepad++.exe'
                    if os.path.exists(npp_path):
                        subprocess.Popen([npp_path, str(youtube_out)])
                        logger.info(f"[OPEN] results.txt opened in Notepad++")
                    else:
                        subprocess.Popen(f'start notepad++ "{youtube_out}"', shell=True)
                        logger.info("[OPEN] results.txt opened via notepad++ command")
            except Exception as e: logger.warning(f"[OPEN] Could not open results in Notepad++: {e}")

            logger.info("="*60); logger.info(" SESSION COMPLETE"); logger.info("="*60); 
            IS_SESSION_DONE = True; await asyncio.sleep(2); break
        else: await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
