import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import the script
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Mock Shazam to avoid side effects on import
from unittest.mock import patch
with patch('shazamio.Shazam'):
    from label_marks_complete import identify_song

class TestIdentifySong(unittest.IsolatedAsyncioTestCase):

    @patch('label_marks_complete.get_optimal_sliding_windows')
    @patch('label_marks_complete.subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.stat')
    @patch('pathlib.Path.unlink')
    async def test_identify_song_sliding(self, mock_unlink, mock_stat, mock_exists, mock_run, mock_get_windows):
        # Setup
        shazam = AsyncMock()
        audio_path = Path("audio.m4a")
        current_sec = 60.0
        gap = 19.0
        snippets_dir = Path("snippets")
        
        # Mock 2 windows
        mock_get_windows.return_value = [(0.0, 12.0), (7.0, 12.0)]
        
        # Mock file exists and has size
        mock_exists.return_value = True
        mock_stat.return_value.st_size = 2000
        
        # Mock Shazam returns nothing for first window, but success for second
        async def mock_recognize(path, timeout=None):
            # The first window will be processed first
            # We can check which window is being processed if we want, 
            # but here we'll just return matches based on call count.
            if mock_recognize.call_count == 1:
                mock_recognize.call_count += 1
                return {"matches": []}
            return {"track": {"title": "Test Title", "subtitle": "Test Artist"}}
        
        mock_recognize.call_count = 1
        shazam.recognize_song.side_effect = mock_recognize
        shazam.recognize.side_effect = mock_recognize

        # Run
        result = await identify_song(shazam, audio_path, current_sec, gap, snippets_dir)
        
        # Verify
        self.assertEqual(result, "Test Title - Test Artist")
        # Should have called shazam twice
        self.assertEqual(mock_recognize.call_count, 2)
        # Should have called subprocess.run twice (once for each window)
        self.assertEqual(mock_run.call_count, 2)

    @patch('label_marks_complete.get_optimal_sliding_windows')
    @patch('label_marks_complete.subprocess.run')
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.stat')
    @patch('pathlib.Path.unlink')
    async def test_identify_song_fails_all(self, mock_unlink, mock_stat, mock_exists, mock_run, mock_get_windows):
        # Setup
        shazam = AsyncMock()
        shazam.recognize_song.return_value = {"matches": []}
        shazam.recognize.return_value = {"matches": []}
        mock_get_windows.return_value = [(0.0, 12.0), (7.0, 12.0)]
        mock_exists.return_value = True
        mock_stat.return_value.st_size = 2000

        # Run
        result = await identify_song(shazam, Path("audio.m4a"), 60.0, 19.0, Path("snippets"))
        
        # Verify
        self.assertEqual(result, "Unidentified")
        self.assertEqual(mock_run.call_count, 2)

if __name__ == '__main__':
    unittest.main()