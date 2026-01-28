import unittest
import sys
from pathlib import Path

# Add parent directory to path to import shared_utils
sys.path.append(str(Path(__file__).resolve().parent.parent))

import shared_utils

class TestSharedUtils(unittest.TestCase):

    def test_parse_ts(self):
        self.assertEqual(shared_utils.parse_ts("10"), 10.0)
        self.assertEqual(shared_utils.parse_ts("1:10"), 70.0)
        self.assertEqual(shared_utils.parse_ts("1:01:10"), 3670.0)
        self.assertEqual(shared_utils.parse_ts("invalid"), 0.0)

    def test_format_song_entry(self):
        self.assertEqual(shared_utils.format_song_entry("Song - Artist"), "Song - Artist")
        self.assertEqual(shared_utils.format_song_entry("Song – Artist"), "Song - Artist") # En dash
        self.assertEqual(shared_utils.format_song_entry("Title - " + "A" * 70), "Title")
        self.assertEqual(shared_utils.format_song_entry(""), "")
        self.assertEqual(shared_utils.format_song_entry(None), "")

    def test_get_optimal_sliding_windows_small_gap(self):
        # Gap 5.0 <= WINDOW_DURATION (10.0)
        windows = shared_utils.get_optimal_sliding_windows(5.0)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0], (0.0, 5.0))

    def test_get_optimal_sliding_windows_center_out(self):
        # Gap 25.0
        # n = ceil(25/7) = 4
        # step = (25-10)/(4-1) = 5.0
        # Linear: (0, 10), (5, 10), (10, 10), (15, 10)
        # mid_index = 4 // 2 = 2
        # center = windows[2] = (10, 10)
        # left = [(0, 10), (5, 10)]
        # right = [(15, 10)]
        # reordered: center, left[-1], right[0], left[-2]
        # reordered: (10, 10), (5, 10), (15, 10), (0, 10)
        # FINAL ATTEMPT: (0, 25)
        windows = shared_utils.get_optimal_sliding_windows(25.0)
        
        # We expect 5 windows (4 linear + 1 full gap)
        self.assertEqual(len(windows), 5)
        self.assertEqual(windows[0], (10.0, 10.0)) # Center
        self.assertEqual(windows[1], (5.0, 10.0))  # Left of center
        self.assertEqual(windows[2], (15.0, 10.0)) # Right of center
        self.assertEqual(windows[3], (0.0, 10.0))  # Far left
        self.assertEqual(windows[4], (0.0, 25.0))  # Full gap

    def test_get_optimal_sliding_windows_exactly_duration(self):
        windows = shared_utils.get_optimal_sliding_windows(10.0)
        self.assertEqual(len(windows), 1)
        self.assertEqual(windows[0], (0.0, 10.0))

if __name__ == '__main__':
    unittest.main()
