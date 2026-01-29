import numpy as np
import scipy.io.wavfile as wav
import scipy.signal as signal
from scipy.fftpack import dct
from scipy.fft import rfft
from scipy.signal import get_window
import subprocess
from pathlib import Path
import os

# --- Constants ---
SR = 16000
FRAME_SIZE = int(0.025 * SR)
HOP_SIZE = int(0.010 * SR)

def get_mfccs_v2(y, sr, n_mfcc=20, frame_norm=False):
    y = np.append(y[0], y[1:] - 0.97 * y[:-1])
    
    # WINDOW-LEVEL NORM (Sounder approach)
    if not frame_norm:
        rms = np.sqrt(np.mean(y**2))
        if rms > 1e-10: y /= rms

    window = get_window("hamming", FRAME_SIZE)
    num_frames = max(1, int(np.ceil(float(np.abs(len(y) - FRAME_SIZE)) / HOP_SIZE)))
    y_padded = np.append(y, np.zeros(num_frames * HOP_SIZE + FRAME_SIZE - len(y)))
    
    # Mel Filterbank
    mel_min, mel_max = 0, 2595 * np.log10(1 + (sr/2) / 700)
    mel_points = np.linspace(mel_min, mel_max, 42)
    hz_points = 700 * (10**(mel_points / 2595) - 1)
    bin_points = np.floor((FRAME_SIZE + 1) * hz_points / sr).astype(int)
    fb = np.zeros((40, int(FRAME_SIZE / 2 + 1)))
    for i in range(1, 41):
        fb[i-1, bin_points[i-1]:bin_points[i]] = (np.arange(bin_points[i-1], bin_points[i]) - bin_points[i-1]) / (bin_points[i] - bin_points[i-1])
        fb[i-1, bin_points[i]:bin_points[i+1]] = (bin_points[i+1] - np.arange(bin_points[i], bin_points[i+1])) / (bin_points[i+1] - bin_points[i])
    
    all_mfccs = []
    for i in range(num_frames):
        frame = y_padded[i*HOP_SIZE : i*HOP_SIZE + FRAME_SIZE] * window
        if frame_norm:
            rms = np.sqrt(np.mean(frame**2))
            if rms > 1e-10: frame /= rms
            
        spec = np.abs(rfft(frame))**2 / FRAME_SIZE
        m_en = np.dot(fb, spec)
        mfcc = dct(np.log10(m_en + 1e-10), type=2, norm='ortho')[:n_mfcc]
        all_mfccs.append(mfcc)
    return np.array(all_mfccs)

def cosine_sim(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def extract(path, start, name, loudnorm=False):
    out = f"math_{name}.wav"
    af = ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11"] if loudnorm else []
    cmd = ["ffmpeg", "-y", "-ss", str(start), "-t", "5.0", "-i", path, 
           "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le"] + af + ["-loglevel", "error", out]
    subprocess.run(cmd, check=True)
    return out

def test_math():
    target_path = "runs/Q-3UGV0peAQ/audio.m4a"
    ensemble_path = "runs/DMZf3To6LNA/audio.m4a"
    
    # Target always uses loudnorm in real script
    t_wav = extract(target_path, 10*60 + 27, "target", loudnorm=True)
    # Database learned from raw snippets
    e_wav = extract(ensemble_path, 4*60 + 21, "ensemble", loudnorm=False)
    s_wav = extract(ensemble_path, 24*60 + 53, "sweet", loudnorm=False)

    _, t_data = wav.read(t_wav); t_y = t_data.astype(np.float32) / 32768.0
    _, e_data = wav.read(e_wav); e_y = e_data.astype(np.float32) / 32768.0
    _, s_data = wav.read(s_wav); s_y = s_data.astype(np.float32) / 32768.0

    print(f"{'Recipe':<40} | {'FP vs Ensemble':<15} | {'FP vs Sweet'}")
    print("-" * 80)

    # 1. Broken (Frame-level Norm)
    t_m1 = get_mfccs_v2(t_y, SR, frame_norm=True)
    e_m1 = get_mfccs_v2(e_y, SR, frame_norm=True)
    s_m1 = get_mfccs_v2(s_y, SR, frame_norm=True)
    
    def get_fp(m):
        v = np.concatenate([np.mean(m[:, 1:], axis=0), np.std(m[:, 1:], axis=0)])
        return v / np.linalg.norm(v)

    print(f"{'1. Broken (Frame-Norm)':<40} | {cosine_sim(get_fp(t_m1), get_fp(e_m1)):.4f}         | {cosine_sim(get_fp(t_m1), get_fp(s_m1)):.4f}")

    # 2. Sound (Window-level Norm + 20 MFCCs)
    t_m2 = get_mfccs_v2(t_y, SR, n_mfcc=20, frame_norm=False)
    e_m2 = get_mfccs_v2(e_y, SR, n_mfcc=20, frame_norm=False)
    s_m2 = get_mfccs_v2(s_y, SR, n_mfcc=20, frame_norm=False)
    
    print(f"{'2. Sound (Window-Norm, 20 MFCCs)':<40} | {cosine_sim(get_fp(t_m2), get_fp(e_m2)):.4f}         | {cosine_sim(get_fp(t_m2), get_fp(s_m2)):.4f}")

    for f in [t_wav, e_wav, s_wav]: Path(f).unlink(missing_ok=True)

if __name__ == "__main__":
    test_math()