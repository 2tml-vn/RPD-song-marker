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
SUBSTRING_OVERRIDE = [
    # (Japanese, English, Optional Artist)
    ("うまぴょい伝説", "Umapyoi Densetsu"),
    ("サインはB", "Sign wa B"),
    ("トレセン音頭", "Tracen Ondo"),
    ("おちゃめ機能", "Mischievous Function"),
    ("アイドル活動!", "Idol Activity!"),
    ("あんさんぶる体操！！", "Ensemble Taisou!!"),
    ("君色に染まる", "kimiiro ni somaru"),
    ("金曜日のおはよう", "Kinyoubi no Ohayou"),
    ("ニッポン笑顔百景", "Nippon Egao Hyakkei"),
    ("FUN☆FUN☆わんだふるDAYS!", "FUN☆FUN☆Wonderful DAYS!"),
    ("ワーワーワールド", "Wah Wah World"),
    ("神のまにまに", "Kamino Manimani", "れるりり"),
    ("Special♡Spell", "", "きゅるりんってしてみて"),
    ("cLick cRack", "", "ギガP"),
    ("夜もすがら君想ふ", "Yomosugara Kimi Omou", "TOKOTOKO(西沢さんP)"),
]

# User-defined phrase replacements: if song name contains the phrase, replace with the set song name
# Format: ("phrase to find", "replacement song name")
USER_PHRASE_REPLACE = [
    ("LOST IN PARADISE", "LOST IN PARADISE (Jujutsu Kaisen Ending Theme Song) [feat. AKLO] - ALI"),
    ("STAR☆T☆RAIN", "STAR☆T☆RAIN"),
    ("Umapyoi Legend", "うまぴょい伝説 (Umapyoi Densetsu) - ウマ娘 プリティーダービー"),
    ("Ensemble Taiso!!", "あんさんぶる体操！！ (Ensemble Taisou!!)"),
    ("MIRACLE WAVE", "MIRACLE WAVE - Aqours",)
]

def apply_substring_remap(full_name):
    if not full_name: return full_name
    for item in SUBSTRING_OVERRIDE:
        ja, en = item[0], item[1]
        artist = f" - {item[2]}" if len(item) > 2 else ""
        # Only check en if it's not empty, otherwise empty string matches everything
        if en:
            if ja in full_name or en in full_name:
                return f"{ja} ({en}){artist}"
        else:
            if ja in full_name:
                return f"{ja}{artist}"
    return full_name

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

JAPANESE_TO_ENGLISH_MAP = {
    "悪ノ娘": "The Daughter of Evil",
    "悪ノ召使": "The Servant of Evil",
    "にこぷり♡女子道": "Nicopuri ♡ Joshidou",
    "コールボーイ": "Call Boy",
    "踊れオーケストラ": "Odore Orchestra",
    "罰ゲーム" : "Batsugame",
    "ハム太郎 とっとこうた": "Hamutaro Tottoko Uta",
    "テレキャスタービーボーイ": "Telecaster B-boy",
    "めっちゃGoing!!": "Meccha Going!!",
    "ドキピポ☆エモーション": "Dokipipo☆Emotion",
    "微熱からMystery": "Binetsu kara Mystery",
    "おこちゃま戦争": "Okochama Sensou",
    "敦盛2011": "Atsumori 2011",
    "잘자요 아가씨": "Good Night Ojosama",
    "最低で最高のParadiso": "Saitei de Saikou no Paradis",
    "トリコリコPLEASE!!": "Torikoriko PLEASE!!",
    "キセキヒカル": "Kiseki Hikaru",
    "ラブノベルス": "Love Novels",
    "未熟DREAMER": "Mijuku DREAMER",
    "想いよひとつになれ": "Omoi yo Hitotsu ni Nare",
    "ダイヤモンドプリンセスの憂鬱": "Diamond Princess no Yuuutsu",
    "乙姫心で恋宮殿": "Otohime Heart de Love Kyuuden",
    "金色千夜夢舞台": "Konjiki Senya Yumebutai",
    "スリリング・ワンウェイ": "Thrilling・One Way",
    "完璧ぐ~のね": "Kanpekigu No Ne",
    "知らないLove*教えてLove": "Shiranai Love*Oshiete Love",
    "夏への扉 Never end ver.": "The Door Towards Summer Never end ver.",
    "思い出以上になりたくて": "Omoide Ijou ni Naritakute",
    "ユメノトビラ": "Yume no Tobira",
    "ぷわぷわーお!": "Puwa Puwa-O!",
    "サンシャインぴっかぴか音頭": "Sanshain Pikkapika Ondo",
    "ベノム": "Venom",
    "フレンド革命": "Friend Revolution",
    "こころのたまご": "Kokoro no Tamago",
    "ハイドアンド·シーク": "Hide And Seek",
    "#あくあ色ぱれっと": "Aqua Iro Paretto",
    "OIDEMASE!!〜極楽〜": "OIDEMASE!!〜gokuraku〜",
    'もぎゅっと"love"で接近中!': "Mogyutto “love” de Sekkin Chuu!",
    "アユミ☆マジカルショータイム": "Ayumi☆Magical Showtime",
    "アイドル活動!": "Idol Activity!",
    "リリリリ★バーニングナイト": "Lily Lily ☆ Burning Night",
    "おジャ魔女カーニバル!!": "Ojamajo Carnival!!",
    "お返事まだカナ?おじさん構文!": "Ohenji Mada Kana? Ojisan Koubun!",
    "これからのSomeday": "Korekara no Someday",
    "さらば、佳き日": "Saraba, Yoki Hi",
    "サインはB": "Sign wa B",
    "スイートマジック": "Sweet Magic",
    "ステップ!": "STEP!",
    "だってだって噫無情": "Datte Datte Aa Mujou",
    "ハッピーシンセサイザ": "Happy Synthesizer",
    "ハレ晴レユカイ": "Hare Hare Yukai",
    "ビターチョコデコレーション": "Bitter Choco Decoration",
    "ぽっぴっぽー": "PoPiPo",
    "まいたけダンス": "Maitake Dance",
    "みんなだいすき": "Minna Daisuki",
    "もっとはやくそれになりたい！": "Motto Hayaku Sore ni Naritai!",
    "メグメグ☆ファイアーエンドレスナイト": "MEGUMEGU☆FIRE ENDLESS NIGHT",
    "メランコリック": "Melancholic",
    "ルカルカ★ナイトフィーバー": "Luka Luka ★ Night Fever",
    "ロミオとシンデレラ": "Romeo and Cinderella",
    "一等星のニュアンス": "Ittousei no Nuance",
    "僕たちはひとつの光": "Bokutachi wa Hitotsu no Hikari",
    "僕らは今のなかで": "Bokura wa Ima no Naka de",
    "全速ドリーマー": "Zensoku Dreamer",
    "君のこころは輝いてるかい?": "Kimi no Kokoro wa Kagayaiteru kai?",
    "君色に染まる": "kimiiro ni somaru",
    "告白実行委員会": "Kokuhaku Jikkou Iinkai",
    "夏色えがおで1,2,Jump!": "Natsuiro Egao de 1,2,Jump!",
    "天使のクローバー": "Tenshi no Clover",
    "妙子": "Taeko",
    "常夏☆サンシャイン": "Tokonatsu☆Sunshine",
    "強風オールバック": "Kyoufuu All Back",
    "恋になりたいAQUARIUM": "Koi ni Naritai AQUARIUM",
    "恋ひ恋ふ縁": "Koi Kou Enishi",
    "悪魔の踊り方": "Akuma no Odorikata",
    "我ら!": "Warera!",
    "劣等上等": "BRING IT ON",
    "妄想感傷代償連盟": "Mousou Kanshou Daishou Renmei",
    "少女交響曲": "Shoujo Koukyoukyoku",
    "輝夜の城で踊りたい": "Kaguya no Shiro de Odoritai",
    "虹色Passions!": "Nijiiro Passions!",
    "骸骨楽団とリリア": "Gaikotsu Gakudan to Lilia",
    "神っぽいな": "God-ish",
    "硝子の花園": "Garasu no Hanazono",
    "金曜日のおはよう": "Kinyoubi no Ohayou",
    "刀ピークリスマスのテーマソング2023": "TouPea Christmas 2023",
    "ノンフィクション!!": "Nonfiction!!",
    "オトモダチフィルム": "Otomodachi Film",
    "自力本願レボリューション": "Jiriki Hongan Revolution",
    "花ハ踊レヤいろはにほ": "Hana wa Odoreya Irohaniho",
    "コンプレックス・イマージュ": "complex image",
    "カレンダーガール": "Calendar Girl",
    "愛してるばんざーい!": "Aishiteru Banzai!",
    "クレイジー・ビート": "Crazy Beat",
    "うまるん体操": "Umarun Taisou",
    "千本桜": "Senbonzakura",
    "まいたけダンス": "Maitake Dance",
    "それは僕たちの奇跡": "Sore wa Bokutachi no Kiseki",
    "えれくとりっく・えんじぇぅ": "Electric Angel",
    "青空Jumping Heart": "Aozora Jumping Heart",
    "シュビドゥビ☆スイーツタイム": "Shubidubi☆Sweets Time",
    "元気全開 DAY! DAY! DAY!": "Genki Zenkai DAY! DAY! DAY!",
}

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

async def map_japanese_to_english(title_clean, track_id, shazam_en=None):
    en_name = None
    for map_key, map_val in JAPANESE_TO_ENGLISH_MAP.items():
        if title_clean.startswith(map_key):
            en_name = map_val
            break
    if not en_name and track_id and shazam_en:
        try:
            en_data = await shazam_en.track_about(int(track_id))
            en_title = en_data['track'].get('title') if isinstance(en_data, dict) and 'track' in en_data else (en_data['title'] if isinstance(en_data, dict) and 'title' in en_data else getattr(en_data, 'title', None))
            if en_title and en_title.lower() != title_clean.lower():
                en_name = en_title
        except: pass
    return en_name

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
                    en_name = await map_japanese_to_english(title_clean, track_id, shazam_en)
                    title_clean, en_name = strip_shared_tags(title_clean, en_name)
                    title_clean = strip_extra_info(title_clean)
                    if en_name: en_name = strip_extra_info(en_name)
                    if en_name and en_name.lower() not in title_clean.lower(): title_clean = f"{title_clean} ({en_name})"
                    full_match_name = f"{title_clean} - {artist}"
                    if full_match_name in SHAZAM_REMAP: full_match_name = SHAZAM_REMAP[full_match_name]
                    full_match_name = apply_substring_remap(full_match_name)
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
                    en_name = await map_japanese_to_english(title_clean, None, shazam_en)
                    title_clean, en_name = strip_shared_tags(title_clean, en_name)
                    title_clean = strip_extra_info(title_clean)
                    if en_name: en_name = strip_extra_info(en_name)
                    if en_name and en_name.lower() not in title_clean.lower(): title_clean = f"{title_clean} ({en_name})"
                    acr_match = f"{title_clean} - {artist}"
                    if acr_match in SHAZAM_REMAP: acr_match = SHAZAM_REMAP[acr_match]
                    acr_match = apply_substring_remap(acr_match)
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
