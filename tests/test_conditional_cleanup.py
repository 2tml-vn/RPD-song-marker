import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
import json
import os
import sys
import asyncio
import shutil

# Add parent directory to path to import label_marks_complete
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Mock dependencies before importing label_marks_complete
with patch('shazamio.Shazam'), \
     patch('dna_matcher.DNAMatcher'), \
     patch('audio_fingerprinter.compute_fingerprint'):
    import label_marks_complete

class TestConditionalCleanup(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.video_id = "test_cleanup_vid"
        self.video_dir = Path("runs") / self.video_id
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.audio_path = self.video_dir / "audio.m4a"
        self.audio_path.touch()

    def tearDown(self):
        if self.video_dir.exists():
            shutil.rmtree(self.video_dir)

    @patch('label_marks_complete.identify_song', new_callable=AsyncMock)
    @patch('label_marks_complete.ensure_audio')
    @patch('label_marks_complete.get_video_id')
    @patch('subprocess.check_output')
    @patch('label_marks_complete.start_server')
    async def test_cleanup_when_all_identified(self, mock_server, mock_probe, mock_get_vid, mock_ensure, mock_identify):
        mock_get_vid.return_value = self.video_id
        mock_ensure.return_value = self.audio_path
        mock_identify.return_value = "Song Name - Artist"
        mock_probe.return_value = b"10.0"

        # Use a real queue and populate it
        real_queue = asyncio.Queue()
        real_queue.put_nowait("1.0")
        real_queue.put_nowait("[FINISH]")
        
        with patch('label_marks_complete.MARK_QUEUE', real_queue):
            # Patch sleep to raise an exception to break the infinite loop after processing
            with patch('label_marks_complete.asyncio.sleep', side_effect=[None, None, InterruptedError]):
                try:
                    await label_marks_complete.main()
                except InterruptedError:
                    pass

        # Check if audio was unlinked
        self.assertFalse(self.audio_path.exists())

    @patch('label_marks_complete.identify_song', new_callable=AsyncMock)
    @patch('label_marks_complete.ensure_audio')
    @patch('label_marks_complete.get_video_id')
    @patch('subprocess.check_output')
    @patch('label_marks_complete.start_server')
    async def test_no_cleanup_when_unidentified(self, mock_server, mock_probe, mock_get_vid, mock_ensure, mock_identify):
        mock_get_vid.return_value = self.video_id
        mock_ensure.return_value = self.audio_path
        mock_identify.return_value = "Unidentified"
        mock_probe.return_value = b"10.0"

        # Use a real queue
        real_queue = asyncio.Queue()
        real_queue.put_nowait("1.0")
        real_queue.put_nowait("[FINISH]")
        
        with patch('label_marks_complete.MARK_QUEUE', real_queue):
            with patch('label_marks_complete.asyncio.sleep', side_effect=[None, None, InterruptedError]):
                try:
                    await label_marks_complete.main()
                except InterruptedError:
                    pass

        # Check if audio was preserved
        # THIS SHOULD FAIL CURRENTLY
        self.assertTrue(self.audio_path.exists())

if __name__ == '__main__':
    unittest.main()