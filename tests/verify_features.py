import unittest
import numpy as np
import sys
from pathlib import Path
import os

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import audio_features
import scipy.io.wavfile as wav

class TestAudioFeatures(unittest.TestCase):

    def test_feature_dimension(self):
        sr = 22050
        y = np.random.normal(0, 0.1, sr * 5) # 5s noise
        dna = audio_features.extract_features(y, sr)
        print(f"DNA Dimensions: {len(dna)}")
        self.assertEqual(len(dna), 147)

    def test_discrimination(self):
        # Comparison between noise and a simulated tone
        sr = 22050
        duration = 5.0
        t = np.linspace(0, duration, int(sr * duration))
        
        y1 = np.sin(2 * np.pi * 440 * t) # Pure tone
        y2 = np.random.normal(0, 0.1, len(t)) # Noise
        
        dna1 = np.array(audio_features.extract_features(y1, sr))
        dna2 = np.array(audio_features.extract_features(y2, sr))
        
        sim = np.dot(dna1, dna2) / (np.linalg.norm(dna1) * np.linalg.norm(dna2))
        print(f"Similarity between Tone and Noise: {sim:.4f}")
        self.assertLess(sim, 0.7)

if __name__ == '__main__':
    unittest.main()
