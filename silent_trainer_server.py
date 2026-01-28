import os
import sys
import json
import librosa
import numpy as np
import joblib
import subprocess
import random
from sklearn.ensemble import RandomForestClassifier
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import warnings

warnings.filterwarnings('ignore')

# --- CONFIGURATION ---
DATA_FILE = "all_training_dna.npz"
MODEL_FILE = "ultimate_song_model.joblib"
SR = 22050
HOP_LENGTH = 512
WINDOW_SEC = 3.0

# Global state
y_audio = None
current_vid = ""

def extract_dna_slice(y, sr, center_sec):
    start_sample = int((center_sec - WINDOW_SEC/2) * sr)
    if start_sample < 0: start_sample = 0
    end_sample = start_sample + int(WINDOW_SEC * sr)
    if end_sample > len(y): end_sample = len(y)
    y_slice = y[start_sample:end_sample]
    if len(y_slice) < 1024: return None

    S = np.abs(librosa.stft(y_slice, hop_length=HOP_LENGTH))
    mfcc = librosa.feature.mfcc(S=librosa.power_to_db(S**2 + 1e-10), sr=sr, n_mfcc=20)
    chroma = librosa.feature.chroma_stft(S=S**2, sr=sr)
    tonnetz = librosa.feature.tonnetz(y=librosa.effects.harmonic(y_slice), sr=sr)
    contrast = librosa.feature.spectral_contrast(S=S, sr=sr)
    flatness = librosa.feature.spectral_flatness(S=S)
    centroid = librosa.feature.spectral_centroid(S=S, sr=sr)
    zcr = librosa.feature.zero_crossing_rate(y_slice, hop_length=HOP_LENGTH)
    onset = librosa.onset.onset_strength(y=y_slice, sr=sr, hop_length=HOP_LENGTH)
    
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
    return np.array(dna)

def silent_finalize(new_X, new_y):
    if not new_X: return
    if os.path.exists(DATA_FILE):
        db = np.load(DATA_FILE)
        X_f = np.vstack([db['X'], new_X]); y_f = np.concatenate([db['y'], new_y])
    else: X_f, y_f = np.array(new_X), np.array(new_y)
    
    np.savez(DATA_FILE, X=X_f, y=y_f)
    clf = RandomForestClassifier(n_estimators=200, max_depth=20, n_jobs=-1, random_state=42)
    clf.fit(X_f, y_f)
    joblib.dump(clf, MODEL_FILE)
    print(f"  [AI] Knowledge updated silently. Database: {len(X_f)} samples.")

class SilentHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global y_audio, current_vid
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        
        if parsed.path == '/add_mark':
            ts = params.get('ts', ['0'])[0]
            vid = params.get('vid', [''])[0]
            
            if ts == '[FINISH]':
                print(f"\n[EVENT] Browser Session Finished for {vid}.")
                self.send_response(200); self.end_headers(); return

            if ts == '[UNDO]':
                print(f"  [EVENT] User Undid last mark. (Note: Database correction not yet implemented for UNDO)")
                self.send_response(200); self.end_headers(); return

            # Switch audio if video changed
            if vid != current_vid:
                print(f"\n[EVENT] Video Changed to {vid}. Loading audio...")
                library_dir = os.path.join("youtube_library", vid)
                os.makedirs(library_dir, exist_ok=True)
                audio_path = os.path.join(library_dir, "audio.webm")
                if not os.path.exists(audio_path):
                    subprocess.run(f'yt-dlp -f \"ba\" -o \"{audio_path}\" \"https://youtu.be/{vid}\""', shell=True)
                y_audio, _ = librosa.load(audio_path, sr=SR)
                current_vid = vid

            try:
                sec = float(ts)
                print(f"  [MARK] Captured at {int(sec//60):02d}:{int(sec%60):02d}")
                
                # 1. Capture Positive
                dna_pos = extract_dna_slice(y_audio, SR, sec)
                # 2. Capture random Negatives from the last 2 minutes
                new_X = [dna_pos]
                new_y = [1]
                for _ in range(2):
                    r_t = max(2.0, sec - random.uniform(5, 120))
                    new_X.append(extract_dna_slice(y_audio, SR, r_t))
                    new_y.append(0)
                
                silent_finalize(new_X, new_y)
            except Exception as e:
                print(f"  [ERROR] {e}")

            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

    def log_message(self, format, *args): return

def main():
    if len(sys.argv) < 2:
        print("Usage: python silent_trainer_server.py <YOUTUBE_ID>")
        return

    vid_id = sys.argv[1]
    global y_audio, current_vid
    
    print(f"\n--- SILENT SHADOW TRAINER ACTIVE ---")
    
    # Pre-load audio for the target ID
    library_dir = os.path.join("youtube_library", vid_id)
    os.makedirs(library_dir, exist_ok=True)
    audio_path = os.path.join(library_dir, "audio.webm")
    
    if not os.path.exists(audio_path):
        print(f"Downloading audio for {vid_id}...")
        subprocess.run(f'yt-dlp -f "ba" -o "{audio_path}" "https://youtu.be/{vid_id}"', shell=True)
    
    print(f"Loading {audio_path} into RAM...")
    y_audio, _ = librosa.load(audio_path, sr=SR)
    current_vid = vid_id

    print(f"Listening on http://localhost:5000")
    print(f"Now go to YouTube video {vid_id} and start marking!")
    server = HTTPServer(('localhost', 5000), SilentHandler)
    server.serve_forever()

if __name__ == "__main__":
    main()
