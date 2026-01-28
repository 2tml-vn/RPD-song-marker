import numpy as np
import scipy.io.wavfile as wav
import scipy.signal as signal
import subprocess
import os

def extract_snippet(vid_id, output_path, filters=None, start_sec=120):
    """Extracts a 10s snippet with optional FFmpeg filters."""
    audio_path = f"runs/{vid_id}/audio.m4a"
    af_cmd = ["-af", filters] if filters else []
    
    cmd = [
        "ffmpeg", "-y", "-ss", str(start_sec), "-t", "10", "-i", audio_path,
        "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le"
    ] + af_cmd + [output_path, "-loglevel", "error"]
    
    subprocess.run(cmd, check=True)

def calculate_sharpness(file_path):
    """Calculates a 'Constellation Density' score."""
    rate, data = wav.read(file_path)
    data = data.astype(np.float32) / 32768.0
    freqs, psd = signal.welch(data, rate, nperseg=1024)
    mask = (freqs >= 1000) & (freqs <= 5000)
    target_psd = psd[mask]
    if len(target_psd) == 0: return 0
    mean_energy = np.mean(target_psd)
    max_energy = np.max(target_psd)
    contrast = np.std(target_psd) / mean_energy if mean_energy > 0 else 0
    return (max_energy / mean_energy) * contrast

def main():
    vid = "C_omZX8X_-A"
    
    # Define our "Sharpness Boost" experimental filter
    # 1. highpass: remove mud
    # 2. equalizer: heavy 10dB boost at the 3.5kHz recognition peak
    # 3. volume: prevent clipping after EQ boost
    boost_filter = "highpass=f=200,equalizer=f=3500:t=q:w=1:g=10,volume=-2dB"

    print(f"--- DNA Sharpness Boost Test ({vid}) ---")
    
    # 1. Original
    extract_snippet(vid, "dna_orig.wav")
    orig_score = calculate_sharpness("dna_orig.wav")
    print(f"ORIGINAL: Sharpness Score = {orig_score:.2f}")
    
    # 2. Boosted
    extract_snippet(vid, "dna_boosted.wav", filters=boost_filter)
    boost_score = calculate_sharpness("dna_boosted.wav")
    print(f"BOOSTED:  Sharpness Score = {boost_score:.2f}")
    
    improvement = ((boost_score - orig_score) / orig_score) * 100
    print(f"\nRESULT: {improvement:.1f}% Improvement in Spectral Clarity")
    
    if boost_score >= 35:
        print("STATUS: SUCCESS! Audio is now in the 'Success Zone' (>35).")
    else:
        print(f"STATUS: Audio improved but still below target 35. Need more tuning.")

    # Cleanup
    for f in ["dna_orig.wav", "dna_boosted.wav"]:
        if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    main()