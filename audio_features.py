import librosa
import numpy as np
import warnings

# Muffle librosa warnings
warnings.filterwarnings('ignore')

def extract_features(y, sr):
    """
    Extracts high-dimensional (150+) audio DNA.
    Includes: MFCC, Chroma, Tonnetz, Spectral Contrast, Flatness, Centroid, ZCR, Onset.
    For each feature, we calculate Mean, StdDev, and Delta (Mean of differences).
    """
    if len(y) == 0:
        return [0.0] * 150

    # 1. Pre-computed Spectrogram for speed
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    S_db = librosa.power_to_db(S**2 + 1e-10)

    # 2. Extract Base Features
    mfcc = librosa.feature.mfcc(S=S_db, sr=sr, n_mfcc=20)
    chroma = librosa.feature.chroma_stft(S=S**2, sr=sr)
    contrast = librosa.feature.spectral_contrast(S=S, sr=sr)
    flatness = librosa.feature.spectral_flatness(S=S)
    centroid = librosa.feature.spectral_centroid(S=S, sr=sr)
    zcr = librosa.feature.zero_crossing_rate(y, frame_length=2048, hop_length=512)
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512).reshape(1, -1)
    
    # Harmonic-Percussive separation for Tonnetz
    y_harm = librosa.effects.harmonic(y)
    tonnetz = librosa.feature.tonnetz(y=y_harm, sr=sr)

    feature_list = [mfcc, chroma, tonnetz, contrast, flatness, centroid, zcr, onset]
    dna = []

    for feat in feature_list:
        # Calculate Mean across time
        dna.extend(np.mean(feat, axis=1))
        # Calculate StdDev across time
        dna.extend(np.std(feat, axis=1))
        
        # Calculate Delta (Mean of absolute differences between frames)
        if feat.shape[1] > 1:
            delta = np.mean(np.abs(np.diff(feat, axis=1)), axis=1)
            dna.extend(delta)
        else:
            dna.extend([0.0] * feat.shape[0])

    # Final L2 Normalization for better matching
    dna = np.array(dna)
    norm = np.linalg.norm(dna)
    if norm > 0:
        dna = dna / norm
        
    return dna.tolist()
