import numpy as np
from scipy.fftpack import dct
from scipy.fft import rfft
from scipy.signal import get_window

def hz_to_mel(f):
    return 2595 * np.log10(1 + f / 700)

def mel_to_hz(m):
    return 700 * (10**(m / 2595) - 1)

def get_mel_filterbank(sr, n_fft, n_mels=40):
    """Calculates a Mel filterbank."""
    mel_min = hz_to_mel(0)
    mel_max = hz_to_mel(sr / 2)
    mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
    hz_points = mel_to_hz(mel_points)
    
    # FFT bins
    bin_points = np.floor((n_fft + 1) * hz_points / sr).astype(int)
    
    filters = np.zeros((n_mels, int(n_fft / 2 + 1)))
    for i in range(1, n_mels + 1):
        # Left slope
        for j in range(bin_points[i-1], bin_points[i]):
            if bin_points[i] != bin_points[i-1]:
                filters[i-1, j] = (j - bin_points[i-1]) / (bin_points[i] - bin_points[i-1])
        # Right slope
        for j in range(bin_points[i], bin_points[i+1]):
            if bin_points[i+1] != bin_points[i]:
                filters[i-1, j] = (bin_points[i+1] - j) / (bin_points[i+1] - bin_points[i])
    return filters

def compute_fingerprint(y, sr):
    """
    Upgraded High-Fidelity Audio DNA.
    Uses 13 MFCCs with Mean and Standard Deviation.
    Returns 26 dimensions.
    """
    if len(y) == 0:
        return [0.0] * 26
        
    # 1. Pre-emphasis (High-pass filter to balance spectrum)
    y = np.append(y[0], y[1:] - 0.97 * y[:-1])
    
    # 2. Framing (25ms windows with 10ms step)
    frame_size = int(0.025 * sr)
    hop_size = int(0.010 * sr)
    if frame_size == 0: return [0.0] * 26
    
    window = get_window("hamming", frame_size)
    
    # Calculate number of frames
    num_frames = max(1, int(np.ceil(float(np.abs(len(y) - frame_size)) / hop_size)))
    
    # Pad signal
    pad_len = num_frames * hop_size + frame_size
    y_padded = np.append(y, np.zeros(pad_len - len(y)))
    
    # Mel Filterbank setup
    n_fft = frame_size
    n_mels = 40
    mel_fb = get_mel_filterbank(sr, n_fft, n_mels)
    
    # 3. FFT and MFCC calculation per frame
    all_mfccs = []
    for i in range(num_frames):
        frame = y_padded[i*hop_size : i*hop_size + frame_size] * window
        # Power Spectrum
        spectrum = np.abs(rfft(frame))**2 / n_fft
        # Mel energies
        mel_energies = np.dot(mel_fb, spectrum)
        # Log mel energies (volume independent due to relative energy distribution)
        log_mel_energies = np.log10(mel_energies + 1e-10)
        # Discrete Cosine Transform (DCT)
        mfcc = dct(log_mel_energies, type=2, norm='ortho')[:13]
        all_mfccs.append(mfcc)
    
    mfccs = np.array(all_mfccs)
    
    # 4. Global Statistics (Mean and Std Dev across the 5s window)
    mean_mfcc = np.mean(mfccs, axis=0)
    std_mfcc = np.std(mfccs, axis=0)
    
    # Normalize features to be strictly 0-1 or centered for stable Cosine Similarity
    # Actually MFCCs are already quite stable for Cosine Similarity.
    # We combine them into a single 26-dim vector.
    fp = np.concatenate([mean_mfcc, std_mfcc])
    
    return fp.tolist()
