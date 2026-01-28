import os
import json
import librosa
import numpy as np
import random
import warnings

warnings.filterwarnings('ignore')

# --- OPTIMIZED CONFIGURATION ---
SR = 22050 
HOP_LENGTH = 512
WINDOW_SEC = 3.0
RUNS_DIR = "runs"
DATA_FILE = "all_training_dna.npz"
LOG_FILE = "harvest_log.json"

def timestamp_to_seconds(ts):
    ts = str(ts).strip()
    if ':' not in ts:
        try: return float(ts)
        except: return 0
    parts = ts.split(':')
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except: return 0
    return 0

def extract_dna_optimized(y_slice, sr):
    """Calculates all 8 sensors using a pre-computed Spectrogram for speed."""
    
    # 1. Pre-compute Spectrum (Shared by MFCC, Chroma, Contrast, Centroid, Flatness)
    S = np.abs(librosa.stft(y_slice, hop_length=HOP_LENGTH))
    
    # 2. Extract Features using S where possible
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(S**2), sr=sr, n_mfcc=20)
    chroma = librosa.feature.chroma_stft(S=S**2, sr=sr)
    contrast = librosa.feature.spectral_contrast(S=S, sr=sr)
    flatness = librosa.feature.spectral_flatness(S=S)
    centroid = librosa.feature.spectral_centroid(S=S, sr=sr)
    
    # 3. Time-Domain features (must use y)
    zcr = librosa.feature.zero_crossing_rate(y_slice, hop_length=HOP_LENGTH)
    onset = librosa.onset.onset_strength(y=y_slice, sr=sr, hop_length=HOP_LENGTH)
    
    # 4. Harmonic features (Needs harmonic component)
    y_harm = librosa.effects.harmonic(y_slice)
    tonnetz = librosa.feature.tonnetz(y=y_harm, sr=sr)
    
    sensor_list = [mfcc, chroma, tonnetz, contrast, flatness, centroid, zcr, onset]
    
    dna = []
    for f in sensor_list:
        if f.ndim > 1:
            dna.extend(np.mean(f, axis=1))
            dna.extend(np.std(f, axis=1))
            mid = f.shape[1] // 2
            if mid > 0:
                dna.extend(np.mean(f[:, mid:], axis=1) - np.mean(f[:, :mid], axis=1))
            else:
                dna.extend(np.zeros(f.shape[0])) # Fallback for tiny slices
        else:
            f_flat = f.flatten()
            dna.append(np.mean(f_flat))
            dna.append(np.std(f_flat))
            mid = len(f_flat) // 2
            if mid > 0:
                dna.append(np.mean(f_flat[mid:]) - np.mean(f_flat[:mid]))
            else:
                dna.append(0)
    return dna

# 1. Load existing database
X_list = []
y_list = []
if os.path.exists(DATA_FILE):
    data = np.load(DATA_FILE)
    X_list = data['X'].tolist()
    y_list = data['y'].tolist()
    print(f"Loaded existing database: {len(X_list)} samples.")

# 2. Load harvest log
history = []
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'r') as f:
        history = json.load(f)

new_count = 0

def harvest_folder(folder_name):
    global new_count
    if folder_name in history:
        return
    
    path = os.path.join(RUNS_DIR, folder_name)
    json_path = os.path.join(path, "progress.json")
    audio_path = None
    for ext in ['.m4a', '.webm', '.wav', '.mp3']:
        test_path = os.path.join(path, f"audio{ext}")
        if os.path.exists(test_path):
            audio_path = test_path
            break
            
    if os.path.exists(json_path) and audio_path:
        print(f"  [OPTIMIZED HARVEST] {folder_name}...")
        try:
            # 1. Fast Check: Read Marks & Duration Metadata FIRST
            with open(json_path, 'r', encoding='utf-8') as f:
                marks = json.load(f)
            positives = [timestamp_to_seconds(ts) for ts in marks.keys()]
            
            if not positives:
                print(f"    [SKIP] No marks found.")
                return

            # Get duration quickly (header only)
            dur = librosa.get_duration(path=audio_path)
            
            # STRICT SAFETY: Skip unfinished videos
            max_marked_sec = max(positives)
            if dur - max_marked_sec > 600:
                print(f"    [SKIP] Unfinished (Gap: {int((dur-max_marked_sec)/60)}m). Skipping load.")
                return

            # 2. Heavy Lift: Load Audio ONLY if valid
            print(f"    - Loading audio...")
            y, sr = librosa.load(audio_path, sr=SR)
            
            win_samples = int(WINDOW_SEC * sr)
            
            # POSITIVES
            print(f"    - Processing {len(positives)} positives...")
            for sec in positives:
                if sec < WINDOW_SEC or sec > dur - WINDOW_SEC: continue
                start_s = int((sec - WINDOW_SEC/2) * sr)
                y_slice = y[start_s : start_s + win_samples]
                
                dna = extract_dna_optimized(y_slice, sr)
                X_list.append(dna)
                y_list.append(1)
            
            # NEGATIVES
            print(f"    - Processing {len(positives) * 2} negatives...")
            got = 0
            while got < len(positives) * 2:
                r_sec = random.uniform(WINDOW_SEC, dur - WINDOW_SEC)
                if any(abs(r_sec - p) < 7 for p in positives): continue
                start_s = int((r_sec - WINDOW_SEC/2) * sr)
                y_slice = y[start_s : start_s + win_samples]
                
                dna = extract_dna_optimized(y_slice, sr)
                X_list.append(dna)
                y_list.append(0)
                got += 1
            
            history.append(folder_name)
            new_count += 1
            print(f"    [SUCCESS] Added samples.")
            del y
        except Exception as e:
            print(f"    [ERROR] {e}")

# 3. Main Loop
print("Scanning RUNS directory...")
for folder in os.listdir(RUNS_DIR):
    if os.path.isdir(os.path.join(RUNS_DIR, folder)):
        harvest_folder(folder)

# 4. Finalize
if new_count > 0:
    print(f"\nAdded {new_count} new folders.")
    # Sanity check vector length
    if len(X_list) > 0:
        v_len = len(X_list[0])
        X_clean = np.array([x for x in X_list if len(x) == v_len])
        y_clean = np.array(y_list[:len(X_clean)])
        np.savez(DATA_FILE, X=X_clean, y=y_clean)
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f)
        print(f"SUCCESS: Database updated. Vector Size: {v_len}")
else:
    print("Database is up to date.")
