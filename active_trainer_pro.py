import os
import sys
import argparse
import json
import librosa
import numpy as np
import joblib
import random
import subprocess
import time
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from joblib import Parallel, delayed
import warnings

# --- MODULAR IMPORTS ---
import audio_dna

warnings.filterwarnings('ignore')

# --- CONFIGURATION ---
DATA_FILE = "all_training_dna.npz"
MODEL_FILE = "ultimate_song_model.joblib"
LOG_FILE = "harvest_log.json"
CACHE_DIR = Path("cache_maps")

def seconds_to_timestamp(seconds):
    m, s = divmod(int(round(float(seconds))), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m}:{s:02d}"

def timestamp_to_seconds(ts):
    ts = str(ts).strip()
    if ts in ["0:00", "0:0", "0"]: return 0.0
    if ':' not in ts:
        try: return float(ts)
        except: return 0
    parts = ts.split(':')
    try:
        if len(parts) == 2: return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3: return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except: return 0
    return 0

def finalize_live(new_X, new_y):
    """Retrains the model with accumulated data."""
    if not new_X: return joblib.load(MODEL_FILE) if os.path.exists(MODEL_FILE) else None
    
    # Filter valid data
    valid = [(x, y) for x, y in zip(new_X, new_y) if x is not None]
    if not valid: return joblib.load(MODEL_FILE) if os.path.exists(MODEL_FILE) else None
    new_X, new_y = zip(*valid)
    
    if os.path.exists(DATA_FILE):
        db = np.load(DATA_FILE); old_X, old_y = db['X'], db['y']
        # Guard: Check for feature mismatch (e.g. if we added new math)
        if len(old_X) > 0 and len(new_X) > 0 and old_X.shape[1] != len(new_X[0]):
            print(f"\n  [GUARD] Feature Mismatch (Old: {old_X.shape[1]}, New: {len(new_X[0])}). Re-training fresh.")
            X_f, y_f = np.array(new_X), np.array(new_y)
        else:
            X_f = np.vstack([old_X, new_X]); y_f = np.concatenate([old_y, new_y])
    else: X_f, y_f = np.array(new_X), np.array(new_y)
    
    print(f"  [TRAIN] Updating Brain with {len(new_X)} new examples...")
    np.savez(DATA_FILE, X=X_f, y=y_f)
    clf = RandomForestClassifier(n_estimators=200, max_depth=20, n_jobs=-1, random_state=42)
    clf.fit(X_f, y_f); joblib.dump(clf, MODEL_FILE)
    return clf

def cluster_predictions(predictions):
    ai_marks = []
    if predictions:
        predictions.sort()
        curr = [predictions[0]]
        for i in range(1, len(predictions)):
            if predictions[i] - curr[-1] < 12.0: curr.append(predictions[i])
            else: ai_marks.append(np.mean(curr)); curr = [predictions[i]]
        ai_marks.append(np.mean(curr))
    return ai_marks

def get_font_filter():
    if sys.platform == 'win32':
        windir = os.environ.get('WINDIR', 'C:\\Windows')
        font_path = os.path.join(windir, 'Fonts', 'consola.ttf').replace('\\', '/')
        if os.path.exists(font_path):
            font_path = font_path.replace(':', '\\:')
            return f"drawtext=fontfile='{font_path}':text='%{{pts\\:hms}}':x=(w-tw)/2:y=h-th-20:fontcolor=white:fontsize=32:box=1:boxcolor=black@0.6:boxborderw=5"
    return "drawtext=text='%{pts\\:hms}':x=(w-tw)/2:y=h-th-20:fontcolor=white:fontsize=32:box=1:boxcolor=black@0.6:boxborderw=5"

def play_clip(video_path, center_time):
    start_t = max(0, center_time - 3.0)
    vf = get_font_filter()
    print(f"  [PLAY] {seconds_to_timestamp(center_time)}...")
    cmd = [
        'ffplay', '-ss', str(start_t), '-t', '6',
        '-vf', vf, '-autoexit', '-loglevel', 'quiet',
        '-x', '800', '-y', '450',
        '-window_title', f"AI Check: {seconds_to_timestamp(center_time)}",
        video_path
    ]
    try: subprocess.run(cmd, check=False)
    except: print("  [ERROR] ffplay failed.")

def find_video_file(library_dir):
    for p in Path(library_dir).glob("video.*"):
        if p.suffix.lower() in ['.mp4', '.webm', '.mkv', '.m4a', '.mov', '.avi']:
            return str(p)
    return None

def get_or_compute_maps(video_path, vid_id):
    """Smart Caching: Loads .npy map if exists, else computes and saves."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path = CACHE_DIR / f"{vid_id}_maps.npy"
    
    # 1. Try Load
    if cache_path.exists():
        try:
            print(f"  [FAST] Loading pre-computed audio maps...")
            return np.load(cache_path, allow_pickle=True).item()
        except Exception as e:
            print(f"  [WARN] Cache corrupted, re-computing... ({e})")
            
    # 2. Compute
    print(f"  [MATH] Computing Audio DNA (One-time setup)...")
    y, sr = librosa.load(video_path, sr=audio_dna.SR, mono=False)
    maps = audio_dna.compute_feature_maps(y, sr)
    
    # 3. Save
    np.save(cache_path, maps)
    return maps

def jrpd_session(vid_id, json_path=None):
    library_dir = Path("youtube_library") / vid_id; library_dir.mkdir(parents=True, exist_ok=True)
    video_path = find_video_file(library_dir)
    
    if not video_path:
        print(f"Downloading Video: {vid_id}...")
        out_tmpl = str(library_dir / "video.%(ext)s")
        cmd = f'yt-dlp -f "bv*[height<=480]+ba/b[height<=480]" -o "{out_tmpl}" "https://youtu.be/{vid_id}"'
        subprocess.run(cmd, shell=True); video_path = find_video_file(library_dir)

    if not video_path: print(f"Error: No video found."); return

    print(f"\n--- ACTIVE TRAINER: BATCH MODE ({vid_id}) ---")
    
    # 1. PRE-PROCESSING (The "One-Time" Wait)
    maps = get_or_compute_maps(video_path, vid_id)
    dur = maps['mfcc'].shape[1] * (audio_dna.HOP_LENGTH / audio_dna.SR) # approx duration
    
    # Generate Time Grid
    cache_times = np.arange(0, dur, 0.5)
    print(f"  [DNA] Extracting vectors for {len(cache_times)} points...")
    
    # Parallel Extraction (Fast)
    dna_array = Parallel(n_jobs=-1)(delayed(audio_dna.extract_dna_from_maps)(maps, t + (audio_dna.WINDOW_SEC/2)) for t in cache_times)
    
    # 2. LOAD STATE
    positives = []
    negatives = []
    
    if json_path is None: json_path = Path("train_data") / f"progress_{vid_id}.json"
    else: json_path = Path(json_path)
    
    if json_path.exists():
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f); positives = sorted([timestamp_to_seconds(k) for k in data.keys()])

    if os.path.exists(MODEL_FILE): 
        clf = joblib.load(MODEL_FILE)
    else:
        print("  [INIT] New Model Created.")
        v_dna = next(d for d in dna_array if d is not None)
        # Dummy init
        clf = RandomForestClassifier(n_estimators=10, max_depth=5).fit([v_dna]*2, [0, 1])

    # 3. BATCH LOOP
    while True:
        valid_idx = [idx for idx, d in enumerate(dna_array) if d is not None]
        if not valid_idx: break
        
        # Scan
        probs = clf.predict_proba([dna_array[i] for i in valid_idx])
        
        # Find Candidates (High Prob + Not marked yet)
        raw_hits = []
        for i, p in enumerate(probs):
            t_sec = cache_times[valid_idx[i]]
            # Skip knowns
            if any(abs(t_sec - p_t) < 2.0 for p_t in positives): continue
            if any(abs(t_sec - n_t) < 2.0 for n_t in negatives): continue
            
            if p[1] > 0.4: # Low threshold to find candidates
                raw_hits.append(t_sec)
        
        ai_marks = cluster_predictions(raw_hits)
        
        # Prioritize suggestions: Top 10 by model confidence (simplified here to first 10 for speed)
        batch = ai_marks[:10] 
        
        if not batch:
            print("\n[IDLE] No new suggestions.")
            choice = input("  [c] Create Manual, [q] Quit: ").strip().lower()
            if choice == 'q': break
            elif choice == 'c':
                ts = input("  Timestamp: "); s = timestamp_to_seconds(ts)
                batch = [s] # Treat manual as a mini-batch
            else: continue

        print(f"\n[BATCH] Reviewing {len(batch)} items...")
        
        new_X_batch = []
        new_y_batch = []
        
        for t_check in batch:
            play_clip(video_path, t_check)
            
            while True:
                ans = input(f"  Song Start at {seconds_to_timestamp(t_check)}? [y/n/r]: ").strip().lower()
                if ans == 'y':
                    positives.append(t_check)
                    idx = np.abs(cache_times - t_check).argmin()
                    
                    # DATA AUGMENTATION: Add Neighbors as Positives
                    # This fixes the "00:04 vs 00:05" issue
                    for offset in [-1, 0, 1]: # -0.5s, 0s, +0.5s
                        n_idx = max(0, min(len(dna_array)-1, idx + offset))
                        if dna_array[n_idx] is not None:
                            new_X_batch.append(dna_array[n_idx])
                            new_y_batch.append(1)
                    break
                    
                elif ans == 'n':
                    negatives.append(t_check)
                    idx = np.abs(cache_times - t_check).argmin()
                    
                    # Add Neighbors as Negatives
                    for offset in [-2, -1, 0, 1, 2]: # Wider net for negatives
                        n_idx = max(0, min(len(dna_array)-1, idx + offset))
                        if dna_array[n_idx] is not None:
                            new_X_batch.append(dna_array[n_idx])
                            new_y_batch.append(0)
                    break
                elif ans == 'r': play_clip(video_path, t_check) # Replay
        
        # ONE TRAIN PER BATCH
        if new_X_batch:
            clf = finalize_live(new_X_batch, new_y_batch)
            
        # Save Progress
        clean_dict = {seconds_to_timestamp(t): "" for t in sorted(list(set(positives)))}
        out_dir = Path("detections") / vid_id; out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "clean_timestamps.json").write_text(json.dumps(clean_dict, indent=4))
        print(f"  [SAVED] Progress updated.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("id"); parser.add_argument("json", nargs='?', default=None)
    jrpd_session(parser.parse_args().id, parser.parse_args().json)