import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add parent directory to path to import the script
sys.path.append(str(Path(__file__).resolve().parent.parent))

from label_marks_complete import ensure_audio

class TestAudioValidation(unittest.TestCase):

    @patch('label_marks_complete.subprocess.check_output')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.stat')
    @patch('pathlib.Path.unlink')
    def test_ensure_audio_truncated(self, mock_unlink, mock_stat, mock_exists, mock_check_output):
        # Setup
        video_id = "test_vid"
        video_dir = Path("runs/test_vid")
        
        # Mock file existence: First it exists (but is bad), then it doesn't (so it "downloads"), then it exists (good)
        # Actually ensure_audio logic is:
        # 1. Check existing. If bad, unlink.
        # 2. If valid existing found, return.
        # 3. Else download.
        
        # Scenario: Existing file is truncated.
        # It should check duration, see mismatch, unlink it, and then proceed to "download" logic.
        # We'll mock the download subprocess.run as well to avoid actual download.
        
        mock_exists.return_value = True
        
        # Mock yt-dlp duration (true duration) -> "10:00" = 600s
        # Mock ffprobe duration (local duration) -> "300.0" (5 mins, truncated)
        
        def check_output_side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "yt-dlp" in cmd_str and "--get-duration" in cmd_str:
                return b"10:00"
            if "ffprobe" in cmd_str:
                return b"300.0"
            return b""
            
        mock_check_output.side_effect = check_output_side_effect
        
        # We need to mock subprocess.run to prevent actual download attempts
        with patch('label_marks_complete.subprocess.run') as mock_run:
            # We want ensure_audio to eventually return a path, assuming download succeeds
            # But strictly for validation, we want to see if unlink was called.
            
            # Since ensure_audio has a loop for extensions, and a download loop, it's complex.
            # Let's focus on the initial validation logic for an existing file.
            
            # If we make the loop fail or break, we can check calls.
            # Let's make it so that after unlink, exists returns False, so it tries to download.
            # Then we can stop.
            
            try:
                ensure_audio(video_id, video_dir)
            except:
                pass # Expected to fail since we didn't mock everything for download
            
            # Verify unlink was called because 300 < 600 - 5
            mock_unlink.assert_called()

    @patch('label_marks_complete.subprocess.check_output')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.stat')
    @patch('pathlib.Path.unlink')
    def test_ensure_audio_valid(self, mock_unlink, mock_stat, mock_exists, mock_check_output):
        # Setup
        video_id = "test_vid"
        video_dir = Path("runs/test_vid")
        
        mock_exists.return_value = True
        
        # Mock yt-dlp duration -> "10:00" = 600s
        # Mock ffprobe duration -> "600.0" (Valid)
        
        def check_output_side_effect(cmd, **kwargs):
            cmd_str = " ".join(cmd)
            if "yt-dlp" in cmd_str and "--get-duration" in cmd_str:
                return b"10:00"
            if "ffprobe" in cmd_str:
                return b"600.0"
            return b""
            
        mock_check_output.side_effect = check_output_side_effect
        
        result = ensure_audio(video_id, video_dir)
        
        # Verify unlink was NOT called
        mock_unlink.assert_not_called()
        self.assertIsNotNone(result)

if __name__ == '__main__':
    unittest.main()
