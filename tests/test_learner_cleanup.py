import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import json
import os
import sys
import shutil

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import learn_songs

class TestLearnerCleanup(unittest.TestCase):

    def setUp(self):
        self.video_id = "test_learner_vid"
        self.video_dir = Path("runs") / self.video_id
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.audio_path = self.video_dir / "audio.m4a"
        self.audio_path.touch()
        
        self.unidentified_file = self.video_dir / "unidentified.json"
        with open(self.unidentified_file, "w") as f:
            json.dump({"00:00": {"end": "00:10", "name": "Test Song"}}, f)

    def tearDown(self):
        if self.video_dir.exists():
            shutil.rmtree(self.video_dir)

    @patch('learn_songs.SongMemoryManager')
    @patch('learn_songs.compute_fingerprint')
    @patch('subprocess.run')
    @patch('scipy.io.wavfile.read')
    def test_cleanup_after_learning(self, mock_wav, mock_run, mock_fp, mock_manager):
        mock_wav.return_value = (16000, MagicMock())
        mock_fp.return_value = [0.1] * 128
        
        # Run learning
        learn_songs.learn_songs(self.video_id)
        
        # Verify audio is deleted
        # THIS SHOULD FAIL CURRENTLY
        self.assertFalse(self.audio_path.exists())

    @patch('learn_songs.SongMemoryManager')
    @patch('learn_songs.compute_fingerprint')
    @patch('subprocess.run')
    @patch('scipy.io.wavfile.read')
    def test_no_cleanup_if_no_names_provided(self, mock_wav, mock_run, mock_fp, mock_manager):
        # Empty names
        with open(self.unidentified_file, "w") as f:
            json.dump({"00:00": {"end": "00:10", "name": ""}}, f)
            
        learn_songs.learn_songs(self.video_id)
        
        # Audio should be preserved if nothing was learned
        self.assertTrue(self.audio_path.exists())

if __name__ == '__main__':
    unittest.main()
