import unittest
import sys
from pathlib import Path

# Add parent directory to path to import shared_utils
sys.path.append(str(Path(__file__).resolve().parent.parent))

import shared_utils

class TestFullGapPipeline(unittest.TestCase):

    def test_12s_gap_windows(self):
        # Gap = 12s. WINDOW_DURATION = 10s.
        # n = ceil(12/7) = 2.
        # Linear: (0, 10), (2, 10).
        # Reorder skips if len <= 2.
        # Final Full Gap: (0, 12).
        windows = shared_utils.get_optimal_sliding_windows(12.0)
        
        self.assertEqual(len(windows), 3)
        self.assertEqual(windows[0], (0.0, 10.0))
        self.assertEqual(windows[1], (2.0, 10.0))
        self.assertEqual(windows[2], (0.0, 12.0))

    def test_8s_gap_windows(self):
        # Gap = 8s <= 10s.
        # Returns only (0, 8).
        windows = shared_utils.get_optimal_sliding_windows(8.0)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0], (0.0, 8.0))

    def test_15s_gap_windows(self):
        # Gap = 15s.
        # n = ceil(15/7) = 3.
        # step = (15-10)/(3-1) = 2.5.
        # Linear: (0, 10), (2.5, 10), (5, 10).
        # mid_index = 3 // 2 = 1.
        # center = windows[1] = (2.5, 10).
        # left = [(0, 10)]. right = [(5, 10)].
        # reordered: (2.5, 10), (0, 10), (5, 10).
        # Final Full Gap: (0, 15).
        windows = shared_utils.get_optimal_sliding_windows(15.0)
        
        self.assertEqual(len(windows), 4)
        self.assertEqual(windows[0], (2.5, 10.0))
        self.assertEqual(windows[1], (0.0, 10.0))
        self.assertEqual(windows[2], (5.0, 10.0))
        self.assertEqual(windows[3], (0.0, 15.0))

if __name__ == '__main__':
    unittest.main()
