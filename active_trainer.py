import numpy as np
import scipy.io.wavfile as wav
import scipy.signal as signal
import subprocess
import os
import optuna
import logging

# Mute Optuna logs to keep it clean
optuna.logging.set_verbosity(optuna.logging.WARNING)

VID_ID = "C_omZX8X_-A"
AUDIO_PATH = f"runs/{VID_ID}/audio.m4a"
TMP_WAV = "ml_tmp.wav"

def calculate_sharpness(file_path):
    """The fitness function for the ML."""
    try:
        rate, data = wav.read(file_path)
        data = data.astype(np.float32) / 32768.0
        # Welch's method for power spectral density
        freqs, psd = signal.welch(data, rate, nperseg=1024)
        # Shazam's sweet spot
        mask = (freqs >= 1000) & (freqs <= 5000)
        target_psd = psd[mask]
        if len(target_psd) == 0: return 0
        mean_e = np.mean(target_psd)
        max_e = np.max(target_psd)
        # Ratio of peaks to noise * contrast
        return (max_e / mean_e) * (np.std(target_psd) / mean_e) if mean_e > 0 else 0
    except:
        return 0

def objective(trial):
    # Search Space
    hp = trial.suggest_int("hp", 50, 800)
    lp = trial.suggest_int("lp", 4000, 12000)
    eq_f = trial.suggest_int("eq_f", 1500, 4500)
    eq_g = trial.suggest_float("eq_g", -5, 15)
    vol = trial.suggest_float("vol", -8, 0)
    
    # Build filter string
    filters = f"highpass=f={hp},lowpass=f={lp},equalizer=f={eq_f}:t=q:w=1:g={eq_g},volume={vol}dB"
    
    # Run FFmpeg (Process 10s from the 2-minute mark)
    cmd = [
        "ffmpeg", "-y", "-ss", "120", "-t", "10", "-i", AUDIO_PATH,
        "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
        "-af", filters, TMP_WAV, "-loglevel", "error"
    ]
    
    try:
        subprocess.run(cmd, check=True)
        score = calculate_sharpness(TMP_WAV)
        return score
    except:
        return 0

def main():
    print(f"--- Training ML for Golden Filter ({VID_ID}) ---")
    print("Running 50 trials to find the best FFmpeg parameters...")
    
    # Use Tree-structured Parzen Estimator (TPE) - Smart search
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=50)
    
    print("\n--- TRAINING COMPLETE ---")
    print(f"Best Score: {study.best_value:.2f}")
    print("Best Parameters:")
    for key, value in study.best_params.items():
        print(f"  {key}: {value}")
    
    # Construct final filter
    p = study.best_params
    final_filter = f"highpass=f={p['hp']},lowpass=f={p['lp']},equalizer=f={p['eq_f']}:t=q:w=1:g={p['eq_g']},volume={p['vol']:.1f}dB"
    print(f"\nGOLDEN FILTER STRING:\n{final_filter}")

    if os.path.exists(TMP_WAV): os.remove(TMP_WAV)

if __name__ == "__main__":
    main()