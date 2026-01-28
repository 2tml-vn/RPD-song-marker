import numpy as np
import librosa
from audio_fingerprinter import compute_fingerprint

def test_fingerprint_consistency():
    # Create random noise
    sr = 22050
    y = np.random.uniform(-1, 1, sr * 5) # 5 seconds
    
    fp1 = compute_fingerprint(y, sr)
    fp2 = compute_fingerprint(y, sr)
    
    assert len(fp1) == 64
    assert np.allclose(fp1, fp2)

def test_fingerprint_difference():
    sr = 22050
    # High frequency noise
    y1 = np.random.uniform(-1, 1, sr * 5)
    y1 = np.append(y1[0], y1[1:] - y1[:-1]) # Sharpen
    
    # Low frequency noise (rolling average)
    y2 = np.random.uniform(-1, 1, sr * 5)
    y2 = np.convolve(y2, np.ones(10)/10, mode='same')
    
    fp1 = compute_fingerprint(y1, sr)
    fp2 = compute_fingerprint(y2, sr)
    
    # Cosine similarity
    sim = np.dot(fp1, fp2) / (np.linalg.norm(fp1) * np.linalg.norm(fp2))
    print(f"Similarity: {sim}")
    assert sim < 0.95
    print("test_fingerprint_difference passed")

if __name__ == "__main__":
    test_fingerprint_consistency()
    test_fingerprint_difference()
    print("All tests passed!")
