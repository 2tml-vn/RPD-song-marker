import numpy as np
import scipy.io.wavfile as wav
import subprocess
from pathlib import Path
import audio_features
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import LabelEncoder
import os

def run_knn_battle():
    # 1. Setup Training Data (The "Database")
    source_audio = "runs/DMZf3To6LNA/audio.m4a"
    songs = [
        ("Ensemble Taisou", "4:21"),
        ("Sweet Sweet", "24:53"),
        ("Fight For Judge", "33:50"),
        ("Kami no Manimani", "41:41"),
        ("Snow halation", "43:24")
    ]
    
    X = []
    y = []
    
    print("Extracting training features...")
    for name, ts in songs:
        tmp = f"train_{name.replace(' ','_')}.wav"
        subprocess.run(["ffmpeg", "-y", "-ss", ts, "-t", "10.0", "-i", source_audio, 
                        "-ar", "22050", "-ac", "1", "-acodec", "pcm_s16le", "-loglevel", "error", tmp], check=True)
        sr, data = wav.read(tmp); y_audio = data.astype(np.float32) / 32768.0
        # Extract multiple windows to build a "cluster"
        for i in range(5):
            start = int(i * 1.0 * sr)
            end = start + int(5.0 * sr)
            dna = audio_features.extract_features(y_audio[start:end], sr)
            X.append(dna)
            y.append(name)
        os.remove(tmp)

    X = np.array(X)
    le = LabelEncoder()
    y_encoded = le.fit_transform(y)

    # Use KNN with distance metric
    knn = KNeighborsClassifier(n_neighbors=3, metric='euclidean')
    knn.fit(X, y_encoded)

    # 2. Test against the WRONG audio (10:27 in Q-3UGV0peAQ)
    print("\nTesting against False Positive segment (10:27)...")
    target_audio = "runs/Q-3UGV0peAQ/audio.m4a"
    tmp_target = "battle_target.wav"
    subprocess.run(["ffmpeg", "-y", "-ss", "10:27", "-t", "10.0", "-i", target_audio, 
                    "-ar", "22050", "-ac", "1", "-acodec", "pcm_s16le", "-loglevel", "error", tmp_target], check=True)
    sr, data = wav.read(tmp_target); y_target = data.astype(np.float32) / 32768.0
    
    target_dna = np.array(audio_features.extract_features(y_target[:int(5.0*sr)], sr)).reshape(1, -1)
    
    # Get distance to nearest neighbor
    distances, indices = knn.kneighbors(target_dna, n_neighbors=1)
    dist = distances[0][0]
    prediction = le.inverse_transform(knn.predict(target_dna))[0]
    
    print(f"Nearest Song: {prediction}")
    print(f"Mathematical Distance: {dist:.4f}")
    
    # Compare to a TRUE match distance
    print("\nTesting against TRUE Match (4:26 in DMZf3To6LNA)...")
    tmp_true = "battle_true.wav"
    subprocess.run(["ffmpeg", "-y", "-ss", "4:26", "-t", "5.0", "-i", source_audio, 
                    "-ar", "22050", "-ac", "1", "-acodec", "pcm_s16le", "-loglevel", "error", tmp_true], check=True)
    sr, data = wav.read(tmp_true); y_true = data.astype(np.float32) / 32768.0
    true_dna = np.array(audio_features.extract_features(y_true, sr)).reshape(1, -1)
    
    dist_true, _ = knn.kneighbors(true_dna, n_neighbors=1)
    print(f"True Match Distance: {dist_true[0][0]:.4f}")

    os.remove(tmp_target)
    os.remove(tmp_true)

if __name__ == "__main__":
    run_knn_battle()