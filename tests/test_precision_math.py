import unittest
import numpy as np
import sys
from pathlib import Path

# Add parent directory to path to import audio_fingerprinter
sys.path.append(str(Path(__file__).resolve().parent.parent))

import audio_fingerprinter

class TestPrecisionMath(unittest.TestCase):

    def test_distinct_signals(self):
        sr = 16000
        duration = 5.0
        t = np.linspace(0, duration, int(sr * duration))
        
        # Signal 1: Pure Sine Wave (440Hz)
        y1 = np.sin(2 * np.pi * 440 * t)
        
        # Signal 2: White Noise
        y2 = np.random.normal(0, 1, len(t))
        
        fp1 = audio_fingerprinter.compute_fingerprint(y1, sr)
        fp2 = audio_fingerprinter.compute_fingerprint(y2, sr)
        
        # Verify dimension
        self.assertEqual(len(fp1), 24)
        self.assertEqual(len(fp2), 24)
        
        # Calculate Cosine Similarity
        fp1 = np.array(fp1)
        fp2 = np.array(fp2)
        sim = np.dot(fp1, fp2) / (np.linalg.norm(fp1) * np.linalg.norm(fp2))
        
        print(f"Similarity between Sine and Noise: {sim:.4f}")
        # They should be very different
        self.assertLess(sim, 0.8)

    def test_volume_independence(self):
        sr = 16000
        duration = 5.0
        t = np.linspace(0, duration, int(sr * duration))
        y = np.sin(2 * np.pi * 440 * t) + np.random.normal(0, 0.1, len(t))
        
        # Signal 1: Original
        fp1 = audio_fingerprinter.compute_fingerprint(y, sr)
        
        # Signal 2: 50% Volume
        fp2 = audio_fingerprinter.compute_fingerprint(y * 0.5, sr)
        
        fp1 = np.array(fp1)
        fp2 = np.array(fp2)
        sim = np.dot(fp1, fp2) / (np.linalg.norm(fp1) * np.linalg.norm(fp2))
        
        print(f"Similarity between Loud and Quiet: {sim:.4f}")
        # Should be almost identical
        self.assertGreater(sim, 0.99)

if __name__ == '__main__':
    unittest.main()
