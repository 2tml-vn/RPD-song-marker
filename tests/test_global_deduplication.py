import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import json
import os
import shutil
import numpy as np
import sqlite3

# Add parent directory to path to import core modules
import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from song_memory_manager import SongMemoryManager
import learn_songs

class TestGlobalDeduplication(unittest.TestCase):

    def setUp(self):
        self.video_id = "test_dedup_vid"
        self.video_dir = Path("runs") / self.video_id
        self.video_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = "test_dedup.db"
        if os.path.exists(self.db_path): os.remove(self.db_path)
        
        self.audio_path = self.video_dir / "audio.m4a"
        self.audio_path.touch()
        
        self.unidentified_file = self.video_dir / "unidentified.json"
        with open(self.unidentified_file, "w") as f:
            json.dump({"00:00": {"end": "00:10", "name": "Dup Song"}}, f)

    def tearDown(self):
        if self.video_dir.exists():
            shutil.rmtree(self.video_dir)
        if os.path.exists(self.db_path):
            try: os.remove(self.db_path)
            except: pass

    @patch('learn_songs.SongMemoryManager')
    @patch('learn_songs.compute_fingerprint')
    @patch('learn_songs.AudioSegment.from_file')
    @patch('subprocess.run')
    @patch('scipy.io.wavfile.read')
    def test_run_twice_deduplication(self, mock_wav, mock_run, mock_pydub, mock_fp, mock_manager_class):
        # Setup real SongMemoryManager but with test path
        real_manager = SongMemoryManager(self.db_path)
        mock_manager_class.return_value = real_manager
        
        mock_wav.return_value = (16000, np.zeros(160000, dtype=np.int16))
        # Ensure identical fingerprints for both runs
        mock_fp.return_value = [0.5] * 64
        
        # --- First Run ---
        learn_songs.learn_songs(self.video_id)
        
        # Manually count signatures
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM signatures")
            count1 = cursor.fetchone()[0]
        
        self.assertGreater(count1, 0, "No signatures were added in first run")
        
        # --- Second Run (Audio must exist again because learn_songs deletes it) ---
        self.audio_path.touch()
        learn_songs.learn_songs(self.video_id)
        
        # Manually count again
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM signatures")
            count2 = cursor.fetchone()[0]
            
        self.assertEqual(count1, count2, f"Second run added {count2 - count1} duplicate signatures")

if __name__ == '__main__':
    unittest.main()
