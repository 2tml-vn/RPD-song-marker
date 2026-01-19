import unittest
import math
import sys
from pathlib import Path

# Add parent directory to path to import the script
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Mock Shazam to avoid side effects on import
from unittest.mock import patch
with patch('shazamio.Shazam'):
    # We will implement this function in the main script
    try:
        from label_marks_complete import get_optimal_sliding_windows
    except ImportError:
        def get_optimal_sliding_windows(gap_size):
            raise NotImplementedError("Function not yet implemented")

class TestSlidingLogic(unittest.TestCase):

    def test_gap_less_than_12(self):
        # Gap = 5s. Should return 1 attempt at offset 0 with full duration.
        windows = get_optimal_sliding_windows(5)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0], (0, 5))

    def test_gap_exactly_12(self):
        # Gap = 12s. Should return 1 attempt at offset 0 with 12s duration.
        windows = get_optimal_sliding_windows(12)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0], (0, 12))

    def test_gap_19s(self):
        # Gap = 19s. 
        # N = ceil(19/10) = 2.
        # Step = (19-12)/(2-1) = 7.
        # Windows: (0, 12), (7, 12)
        windows = get_optimal_sliding_windows(19)
        self.assertEqual(len(windows), 2)
        self.assertEqual(windows[0], (0, 12))
        self.assertEqual(windows[1], (7, 12))

    def test_gap_25s(self):
        # Gap = 25s.
        # N = ceil(25/10) = 3.
        # Step = (25-12)/(3-1) = 6.5.
        # Windows: (0, 12), (6.5, 12), (13, 12)
        windows = get_optimal_sliding_windows(25)
        self.assertEqual(len(windows), 3)
        self.assertEqual(windows[0], (0, 12))
        self.assertEqual(windows[1], (6.5, 12))
        self.assertEqual(windows[2], (13, 12))

    def test_gap_large_capped(self):
        # Gap = 120s.
        # N = clamp(ceil(120/10), 2, 10) = 10.
        # Step = (120-12)/(10-1) = 108/9 = 12.
        windows = get_optimal_sliding_windows(120)
        self.assertEqual(len(windows), 10)
        self.assertEqual(windows[0], (0, 12))
        self.assertEqual(windows[-1], (108, 12))

if __name__ == '__main__':
    unittest.main()
