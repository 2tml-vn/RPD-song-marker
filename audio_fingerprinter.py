import numpy as np
from scipy.fft import rfft, rfftfreq
from scipy.signal import get_window

def compute_fingerprint(y, sr):
    """
    Pure NumPy/SciPy implementation of a spectral fingerprint.
    Avoids Librosa/Numba version issues.
    Returns 64 dimensions.
    """
    if len(y) == 0:
        return [0.0] * 64
        
    # 1. Pre-emphasis
    y = np.append(y[0], y[1:] - 0.97 * y[:-1])
    
    # 2. Frame the signal (approx 23ms frames)
    frame_size = int(0.025 * sr)
    hop_size = int(0.010 * sr)
    window = get_window("hamming", frame_size)
    
    # Calculate number of frames
    num_frames = max(1, int(np.ceil(float(np.abs(len(y) - frame_size)) / hop_size)))
    
    # Pad signal
    pad_len = num_frames * hop_size + frame_size
    y_padded = np.append(y, np.zeros(pad_len - len(y)))
    
    # FFT
    all_spectra = []
    for i in range(num_frames):
        frame = y_padded[i*hop_size : i*hop_size + frame_size] * window
        spectrum = np.abs(rfft(frame))
        all_spectra.append(spectrum)
    
    spectra = np.array(all_spectra)
    freqs = rfftfreq(frame_size, 1/sr)
    
    # 3. Features
    # 3.1 Spectral Centroid (mean over time)
    magnitudes = np.sum(spectra, axis=0)
    centroid = np.sum(freqs * magnitudes) / np.sum(magnitudes) if np.sum(magnitudes) > 0 else 0
    
    # 3.2 Spectral Flatness
    # (Geometric Mean / Arithmetic Mean)
    # Using time-averaged spectrum for stability
    avg_spectrum = np.mean(spectra, axis=0) + 1e-10
    flatness = np.exp(np.mean(np.log(avg_spectrum))) / np.mean(avg_spectrum)
    
    # 3.3 Zero Crossing Rate
    zcr = np.mean(np.abs(np.diff(np.sign(y)))) / 2
    
    # 3.4 Multi-band energy (Simplified Mel-bands)
    # Divide 0-8000Hz into 61 bands
    bands = np.linspace(0, min(sr/2, 8000), 62)
    band_energies = []
    for i in range(len(bands)-1):
        mask = (freqs >= bands[i]) & (freqs < bands[i+1])
        if np.any(mask):
            energy = np.mean(spectra[:, mask])
        else:
            energy = 0.0
        band_energies.append(energy)
        
    # Log scale energies
    band_energies = np.log10(np.array(band_energies) + 1e-10)
    
    # Combine (Centroid + Flatness + ZCR + 61 bands) = 64
    # Wait, 1 + 1 + 1 + 61 = 64. Correct.
    fp = np.concatenate([[centroid/sr, flatness, zcr], band_energies])
    
    return fp.tolist()