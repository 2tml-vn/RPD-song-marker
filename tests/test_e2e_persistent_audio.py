import unittest
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
import json
import os
import sys
import asyncio
import shutil
import numpy as np

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Mock dependencies before importing
with patch('shazamio.Shazam'), \
     patch('dna_matcher.DNAMatcher'), \
     patch('audio_fingerprinter.compute_fingerprint'):
    import label_marks_complete
    import learn_songs

class TestE2EPersistentAudio(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.video_id = "test_e2e_vid"
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
    @patch('learn_songs.SongMemoryManager')
    @patch('learn_songs.compute_fingerprint')
    @patch('learn_songs.wav.read')
    @patch('learn_songs.subprocess.run')
    async def test_full_workflow(self, mock_learn_sub, mock_learn_wav, mock_learn_fp, mock_learn_manager, 
                               mock_server, mock_probe, mock_get_vid, mock_ensure, mock_identify):
        
        # --- PART 1: label_marks_complete ---
        mock_get_vid.return_value = self.video_id
        mock_ensure.return_value = self.audio_path
        mock_identify.return_value = "Unidentified"
        mock_probe.return_value = b"10.0"

        real_queue = asyncio.Queue()
        real_queue.put_nowait("1.0")
        real_queue.put_nowait("[FINISH]")
        
        with patch('label_marks_complete.MARK_QUEUE', real_queue):
            with patch('label_marks_complete.asyncio.sleep', side_effect=[None, None, InterruptedError]):
                try:
                    await label_marks_complete.main()
                except InterruptedError:
                    pass

        # Verify audio exists and unidentified.json is created
        self.assertTrue(self.audio_path.exists())
        self.assertTrue((self.video_dir / "unidentified.json").exists())

        # --- PART 2: learn_songs ---
        # Mock some manual input in unidentified.json
        with open(self.video_dir / "unidentified.json", "r") as f:
            data = json.load(f)
        for ts in data:
            data[ts]["name"] = "Learned Song"
        with open(self.video_dir / "unidentified.json", "w") as f:
            json.dump(data, f)

        mock_learn_wav.return_value = (16000, np.zeros(16000, dtype=np.int16))
        mock_learn_fp.return_value = [0.1] * 128
        
        # We need to mock ffprobe again inside learn_songs if it's called
        with patch('learn_songs.subprocess.check_output', return_value=b"15.0"):
            learn_songs.learn_songs(self.video_id)

        # Verify audio is finally deleted
        self.assertFalse(self.audio_path.exists())

if __name__ == '__main__':
    unittest.main()
