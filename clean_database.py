import os
import numpy as np
import joblib
import librosa
from sklearn.ensemble import RandomForestClassifier
import audio_dna
import sys

# Configuration
DATA_FILE = "all_training_dna.npz"
MODEL_FILE = "ultimate_song_model.joblib"

def timestamp_to_seconds(ts):
    ts = str(ts).strip()
    if ':' not in ts:
        try: return float(ts)
        except: return 0
    parts = ts.split(':')
    try:
        if len(parts) == 2: return int(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3: return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except: return 0
    return 0

def clean():
    if not os.path.exists(DATA_FILE):
        print("Error: No database file found.")
        return

    print("--- AI DATABASE SURGERY (UNDO BUTTON) ---")
    ts_input = input("Enter the timestamp you want to DELETE from AI memory (MM:SS): ").strip()
    sec = timestamp_to_seconds(ts_input)
    
    if sec == 0 and ts_input != "00:00" and ts_input != "0:0":
        print("Invalid timestamp.")
        return

    # 1. Load Data
    db = np.load(DATA_FILE)
    X = db['X']
    y = db['y']
    
    print(f"Current Database Size: {len(X)}")

    # 2. We need a reference audio to find the DNA pattern to delete
    # (Since we don't store timestamps in the .npz, we have to find the pattern)
    # The user should ideally tell us WHICH video it came from
    vid_id = input("Which YouTube ID did this mistake come from?: ").strip()
    library_dir = os.path.join("youtube_library", vid_id)
    audio_path = os.path.join(library_dir, "audio.webm")
    
    if not os.path.exists(audio_path):
        print(f"Error: Audio not found for {vid_id}. I need it to identify the DNA pattern.")
        return

    print(f"Extracting DNA pattern for {ts_input}...")
    y_audio, sr = librosa.load(audio_path, sr=audio_dna.SR, mono=False)
    maps = audio_dna.compute_feature_maps(y_audio, sr)
    dna_to_find = audio_dna.extract_dna_from_maps(maps, sec)

    if dna_to_find is None:
        print("Error extracting DNA for that time.")
        return

    # 3. Find match in database using Euclidean distance
    distances = np.linalg.norm(X - dna_to_find, axis=1)
    match_idx = np.argmin(distances)
    min_dist = distances[match_idx]

    if min_dist > 1.0: # If distance is too high, it's not a real match
        print(f"Could not find a close match in the database (Dist: {min_dist:.2f}).")
        return

    print(f"Found match at index {match_idx} (Dist: {min_dist:.4f}).")
    confirm = input(f"Delete this snapshot from memory? [y/n]: ").strip().lower()
    
    if confirm == 'y':
        new_X = np.delete(X, match_idx, axis=0)
        new_y = np.delete(y, match_idx, axis=0)
        
        # Save
        np.savez(DATA_FILE, X=new_X, y=new_y)
        print(f"Deleted. New database size: {len(new_X)}")
        
        # Retrain
        print("Retraining Brain...")
        clf = RandomForestClassifier(n_estimators=200, max_depth=20, n_jobs=-1, random_state=42)
        clf.fit(new_X, new_y)
        joblib.dump(clf, MODEL_FILE)
        print("SUCCESS: AI has forgotten the mistake.")

if __name__ == "__main__":
    clean()
