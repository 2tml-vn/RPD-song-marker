import numpy as np
import scipy.io.wavfile as wav
from scipy.fftpack import dct
from scipy.fft import rfft
from scipy.signal import get_window
import subprocess
from pathlib import Path

SR = 16000
FRAME_SIZE = int(0.025 * SR)
HOP_SIZE = int(0.010 * SR)

def get_mfccs(y, sr, n_mfcc=20):
    y = np.append(y[0], y[1:] - 0.97 * y[:-1]) # Pre-emphasis
    rms = np.sqrt(np.mean(y**2))
    if rms > 1e-10: y /= rms # Window-level norm
    
    num_frames = max(1, int(np.ceil(float(np.abs(len(y) - FRAME_SIZE)) / HOP_SIZE)))
    y_padded = np.append(y, np.zeros(num_frames * HOP_SIZE + FRAME_SIZE - len(y)))
    
    mel_min, mel_max = 0, 2595 * np.log10(1 + (sr/2) / 700)
    mel_points = np.linspace(mel_min, mel_max, 42)
    hz_points = 700 * (10**(mel_points / 2595) - 1)
    bin_points = np.floor((FRAME_SIZE + 1) * hz_points / sr).astype(int)
    fb = np.zeros((40, int(FRAME_SIZE / 2 + 1)))
    for i in range(1, 41):
        fb[i-1, bin_points[i-1]:bin_points[i]] = (np.arange(bin_points[i-1], bin_points[i]) - bin_points[i-1]) / (bin_points[i] - bin_points[i-1])
        fb[i-1, bin_points[i]:bin_points[i+1]] = (bin_points[i+1] - np.arange(bin_points[i], bin_points[i+1])) / (bin_points[i+1] - bin_points[i])
    
    all_mfccs = []
    window = get_window("hamming", FRAME_SIZE)
    for i in range(num_frames):
        frame = y_padded[i*HOP_SIZE : i*HOP_SIZE + FRAME_SIZE] * window
        spec = np.abs(rfft(frame))**2 / FRAME_SIZE
        mfcc = dct(np.log10(np.dot(fb, spec) + 1e-10), type=2, norm='ortho')[:n_mfcc+1]
        all_mfccs.append(mfcc)
    return np.array(all_mfccs)

def cosine_sim(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def extract(path, start):
    out = f"surgical_{start.replace(':','_')}.wav"
    subprocess.run(["ffmpeg", "-y", "-ss", start, "-t", "5.0", "-i", path, "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le", "-loglevel", "error", out], check=True)
    return out

def run_test():
    target_path = "runs/Q-3UGV0peAQ/audio.m4a" # The file with false positives
    source_path = "runs/DMZf3To6LNA/audio.m4a" # The file with real songs
    
    # 1. Extract audio
    t_wav = extract(target_path, "11:19") # The Ghost Window
    e_wav = extract(source_path, "4:21")  # Real Ensemble Taisou
    s_wav = extract(source_path, "24:53") # Real Sweet Sweet White Song
    
    _, t_d = wav.read(t_wav); t_y = t_d.astype(np.float32) / 32768.0
    _, e_d = wav.read(e_wav); e_y = e_d.astype(np.float32) / 32768.0
    _, s_d = wav.read(s_wav); s_y = s_d.astype(np.float32) / 32768.0
    
    t_m = get_mfccs(t_y, SR, 20)
    e_m = get_mfccs(e_y, SR, 20)
    s_m = get_mfccs(s_y, SR, 20)

    print(f"Goal: Minimize Similarity between Ghost (11:19) and Sweet Sweet (24:53)")
    print("-" * 80)

    # RECIPE 1: Current (Mean + StdDev of MFCC 1-20)
    def recipe_1(m):
        v = np.concatenate([np.mean(m[:, 1:], axis=0), np.std(m[:, 1:], axis=0)])
        return v / np.linalg.norm(v)
    
    print(f"1. Current (Mean+Std): {cosine_sim(recipe_1(t_m), recipe_1(s_m)):.4f} (FAIL - 0.93)")

    # RECIPE 2: Velocity-Only (Discard Mean, use StdDev + Mean of Deltas)
    def recipe_2(m):
        delta = np.diff(m, axis=0)
        # We discard the "Average Sound" (Mean) and only use the "Movement"
        v = np.concatenate([np.std(m[:, 1:], axis=0), np.mean(delta[:, 1:], axis=0)])
        return v / np.linalg.norm(v)
    
    print(f"2. Velocity-Only (StdDev+Delta): {cosine_sim(recipe_2(t_m), recipe_2(s_m)):.4f}")

    # RECIPE 3: High-Frequency Texture (Use MFCC 10-20 only)
    # Lower MFCCs are "Genre Color". Higher MFCCs are "Unique Texture".
    def recipe_3(m):
        v = np.concatenate([np.mean(m[:, 10:], axis=0), np.std(m[:, 10:], axis=0)])
        return v / np.linalg.norm(v)
    
    print(f"3. High-Freq Texture (MFCC 10-20): {cosine_sim(recipe_3(t_m), recipe_3(s_m)):.4f}")

    # RECIPE 4: Z-Score Whitening
    def recipe_4(m):
        # Subtract mean and divide by std dev for every band
        # This forces every band to have equal importance
        whitened = (m - np.mean(m, axis=0)) / (np.std(m, axis=0) + 1e-10)
        v = np.mean(whitened[:, 1:], axis=0) # Should be zeros, let's use std of whitened
        # Actually, let's use the Mean of the log-energies after whitening
        v = np.std(whitened[:, 1:], axis=0)
        return v / np.linalg.norm(v)
    
    print(f"4. Whitened Texture: {cosine_sim(recipe_4(t_m), recipe_4(s_m)):.4f}")

    for f in [t_wav, e_wav, s_wav]: Path(f).unlink(missing_ok=True)

if __name__ == "__main__":
    run_test()