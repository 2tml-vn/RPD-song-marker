import os
import sys
import json
import librosa
import numpy as np
import joblib
import subprocess
from sklearn.ensemble import RandomForestClassifier
import warnings

warnings.filterwarnings('ignore')

# --- CONFIGURATION ---
DATA_FILE = "all_training_dna.npz"
MODEL_FILE = "ultimate_song_model.joblib"
SR = 22050
HOP_LENGTH = 512
WINDOW_SEC = 3.0

def extract_dna_optimized(y_slice, sr):
    """Calculates all 8 sensors using a pre-computed Spectrogram."""
    S = np.abs(librosa.stft(y_slice, hop_length=HOP_LENGTH))
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(S**2 + 1e-10), sr=sr, n_mfcc=20)
    chroma = librosa.feature.chroma_stft(S=S**2, sr=sr)
    contrast = librosa.feature.spectral_contrast(S=S, sr=sr)
    flatness = librosa.feature.spectral_flatness(S=S)
    centroid = librosa.feature.spectral_centroid(S=S, sr=sr)
    zcr = librosa.feature.zero_crossing_rate(y_slice, hop_length=HOP_LENGTH)
    onset = librosa.onset.onset_strength(y=y_slice, sr=sr, hop_length=HOP_LENGTH)
    y_harm = librosa.effects.harmonic(y_slice)
    tonnetz = librosa.feature.tonnetz(y=y_harm, sr=sr)
    
    sensor_list = [mfcc, chroma, tonnetz, contrast, flatness, centroid, zcr, onset]
    dna = []
    for f in sensor_list:
        if f.ndim > 1:
            dna.extend(np.mean(f, axis=1))
            dna.extend(np.std(f, axis=1))
            mid = f.shape[1] // 2
            if mid > 0: dna.extend(np.mean(f[:, mid:], axis=1) - np.mean(f[:, :mid], axis=1))
            else: dna.extend(np.zeros(f.shape[0]))
        else:
            f_flat = f.flatten()
            dna.append(np.mean(f_flat))
            dna.append(np.std(f_flat))
            mid = len(f_flat) // 2
            if mid > 0: dna.append(np.mean(f_flat[mid:]) - np.mean(f_flat[:mid]))
            else: dna.append(0)
    return dna

def main():
    if len(sys.argv) < 2:
        print("Usage: python train_and_apply.py <YOUTUBE_ID>")
        return

    vid_id = sys.argv[1]
    
    # Audio Library (Central folder for all downloads)
    library_dir = os.path.join("youtube_library", vid_id)
    if not os.path.exists(library_dir):
        os.makedirs(library_dir)

    # Detections Directory (Equivalent to results folder in label_marks_complete)
    results_dir = os.path.join("detections", vid_id)
    if not os.path.exists(results_dir):
        os.makedirs(results_dir)

    # 1. DOWNLOAD AUDIO IF MISSING IN LIBRARY
    audio_path = None
    for ext in ['.webm', '.m4a', '.mp3', '.wav']:
        test_path = os.path.join(library_dir, f"audio{ext}")
        if os.path.exists(test_path):
            audio_path = test_path
            break
    
    if not audio_path:
        print(f"Downloading audio to library: {library_dir}...")
        audio_path = os.path.join(library_dir, "audio.webm")
        cmd = f'yt-dlp -f "ba" -o "{audio_path}" "https://youtu.be/{vid_id}"'
        subprocess.run(cmd, shell=True)

    # 2. TRAIN / LOAD MODEL
    if not os.path.exists(DATA_FILE):
        print(f"Error: {DATA_FILE} not found. Run smart_harvester.py first.")
        return

    print("Loading AI Brain...")
    data = np.load(DATA_FILE)
    X, y = data['X'], data['y']
    
    clf = RandomForestClassifier(n_estimators=200, max_depth=20, n_jobs=-1, random_state=42)
    print(f"Training on {len(X)} samples...")
    clf.fit(X, y)
    joblib.dump(clf, MODEL_FILE)

    # 3. APPLY TO VIDEO
    print(f"Scanning Audio from Library: {audio_path}...")
    y_audio, sr = librosa.load(audio_path, sr=SR)
    
    step_sec = 1.0 # 1-second steps for the main scan
    win_samples = int(WINDOW_SEC * sr)
    step_samples = int(step_sec * sr)
    
    predictions = []
    print("  - Running AI Scanner...")
    total_steps = (len(y_audio) - win_samples) // step_samples
    hits = 0
    
    for count, i in enumerate(range(0, len(y_audio) - win_samples, step_samples)):
        # Progress log every 60 steps (~1 minute of video time)
        if count % 60 == 0:
            pct = (count / total_steps) * 100
            curr_m = int((i/sr)//60)
            curr_s = int((i/sr)%60)
            print(f"    [SCAN] {curr_m:02d}:{curr_s:02d} | {pct:.1f}% Complete | Found: {hits}")

        y_slice = y_audio[i : i + win_samples]
        dna = extract_dna_optimized(y_slice, sr)
        
        # Get probability of being a "Song Start"
        prob = clf.predict_proba([dna])[0][1]
        if prob > 0.4:
            t = i / sr + (WINDOW_SEC / 2)
            predictions.append((t, prob))
            hits += 1

    # 4. REFINE AND SAVE
    print("  - Refining timestamps...")
    final_marks = []
    if predictions:
        predictions.sort(key=lambda x: x[0])
        clusters = []
        if predictions:
            curr = [predictions[0]]
            for i in range(1, len(predictions)):
                if predictions[i][0] - curr[-1][0] < 15.0:
                    curr.append(predictions[i])
                else:
                    clusters.append(curr)
                    curr = [predictions[i]]
            clusters.append(curr)
            
            for c in clusters:
                winner = max(c, key=lambda x: x[1])
                if winner[1] > 0.55: # Confidence threshold
                    final_marks.append(winner[0])

    output_path = os.path.join(results_dir, "detected_marks.txt")
    with open(output_path, "w") as f:
        for t in sorted(final_marks):
            ts = f"{int(t//60):02d}:{int(t%60):02d}"
            f.write(f"{ts}\n")
            print(f"  [FOUND] {ts}")

    print(f"\nSUCCESS: Found {len(final_marks)} songs. Results saved to {output_path}")

if __name__ == "__main__":
    main()
