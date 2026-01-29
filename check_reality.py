import sqlite3
import json
import numpy as np
import scipy.io.wavfile as wav
import subprocess
from pathlib import Path
from audio_fingerprinter import compute_fingerprint

def check_reality():
    # 1. Check DB Cross-Similarity
    conn = sqlite3.connect('song_memory.db')
    cursor = conn.cursor()
    cursor.execute("SELECT s.name, sig.fingerprint FROM signatures sig JOIN songs s ON sig.song_id = s.id")
    rows = cursor.fetchall()
    conn.close()
    
    sigs = []
    for name, fp_json in rows:
        sigs.append((name, np.array(json.loads(fp_json))))
    
    print(f"--- DB Consistency Check ({len(sigs)} signatures) ---")
    
    # Compare first signature of Ensemble Taisou vs first of Sweet Sweet White Song
    ensemble_sigs = [fp for name, fp in sigs if "Ensemble" in name]
    sweet_sigs = [fp for name, fp in sigs if "Sweet" in name]
    
    if ensemble_sigs and sweet_sigs:
        e1 = ensemble_sigs[0]
        s1 = sweet_sigs[0]
        sim = np.dot(e1, s1) / (np.linalg.norm(e1) * np.linalg.norm(s1))
        print(f"Similarity between 'Ensemble' and 'Sweet Sweet' in YOUR DB: {sim:.4f}")
        if sim > 0.9:
            print("CRITICAL: Your database signatures are already 90% identical! The math is failing to separate them during learning.")

    # 2. Test the EXACT window from your log (10:27 + 52s = 11:19)
    target_audio = "runs/Q-3UGV0peAQ/audio.m4a"
    tmp_wav = "reality_target.wav"
    # Use the exact extraction from label_marks_complete (Raw, no filters)
    subprocess.run(["ffmpeg", "-y", "-ss", "11:19", "-t", "5.0", "-i", target_audio, 
                    "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", "-loglevel", "error", tmp_wav], check=True)
    
    sr, data = wav.read(tmp_wav)
    y = data.astype(np.float32) / 32768.0
    target_fp = np.array(compute_fingerprint(y, sr))
    
    print(f"\n--- Testing the 11:19 Ghost Window ---")
    best_sim = 0
    best_name = ""
    for name, sig_fp in sigs:
        sim = np.dot(target_fp, sig_fp) / (np.linalg.norm(target_fp) * np.linalg.norm(sig_fp))
        if sim > best_sim:
            best_sim = sim
            best_name = name
            
    print(f"Best Match for 11:19 against DB: {best_name} ({best_sim:.4f})")
    
    Path(tmp_wav).unlink(missing_ok=True)

if __name__ == "__main__":
    check_reality()
