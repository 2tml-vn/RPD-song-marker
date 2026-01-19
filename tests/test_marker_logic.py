import unittest
from unittest.mock import MagicMock
import sys
from pathlib import Path

# Add parent directory to path to import the script
sys.path.append(str(Path(__file__).resolve().parent.parent))

# We need to mock things before importing to avoid side effects
from unittest.mock import patch
with patch('shazamio.Shazam'):
    from label_marks_complete import format_timestamp_for_youtube, parse_ts

class TestMarkerLogic(unittest.TestCase):

    def test_marker_selection(self):
        # Setup mock results
        results = {
            "0:00": "Song 1",
            "1:00": "Processing...",
            "2:00": "Unidentified",
            "3:00": "Processing..."
        }
        insertion_order = ["0:00", "1:00", "2:00", "3:00"]
        is_finished = False
        
        # Simulate the logic in main()
        sorted_keys = sorted(results.keys(), key=parse_ts)
        
        def get_target(res, order, finished):
            target = None
            for m in sorted_keys:
                if res[m] == "Processing...":
                    is_most_recent = (order and m == order[-1])
                    if not is_most_recent or finished:
                        target = m
                        break
            return target

        # Scenario 1: Not finished. Should pick 1:00 but NOT 3:00 (most recent)
        target = get_target(results, insertion_order, False)
        self.assertEqual(target, "1:00")
        
        # Scenario 2: Finished. Should pick 1:00
        target = get_target(results, insertion_order, True)
        self.assertEqual(target, "1:00")
        
        # Scenario 3: After 1:00 is done, should pick 3:00 if finished
        results["1:00"] = "Song 2"
        target = get_target(results, insertion_order, True)
        self.assertEqual(target, "3:00")
        
        # Scenario 4: After 1:00 is done, should NOT pick 3:00 if NOT finished (still most recent)
        target = get_target(results, insertion_order, False)
        self.assertIsNone(target)

if __name__ == '__main__':
    unittest.main()
