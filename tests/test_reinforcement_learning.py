import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
from pathlib import Path
import json
import numpy as np
import scipy.io.wavfile as wav
import os
import shutil

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import learn_songs
import label_marks_complete
import shared_utils
from song_memory_manager import SongMemoryManager

class TestReinforcementLearning(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.test_vid = "test_video_reinforce"
        self.run_dir = Path("runs") / self.test_vid
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = "test_song_memory.db"
        if os.path.exists(self.db_path): os.remove(self.db_path)
        
        # Create a dummy audio file
        self.audio_path = self.run_dir / "audio.m4a"
        # We'll just create a tiny valid wav file and rename it to .m4a 
        # (FFmpeg might complain but we'll mock FFmpeg anyway)
        with open(self.audio_path, "wb") as f: f.write(b"dummy audio content")

    def tearDown(self):
        if self.run_dir.exists(): shutil.rmtree(self.run_dir)
        if os.path.exists(self.db_path): os.remove(self.db_path)

    async def test_learn_and_identify(self):
        # 1. Create unidentified.json
        unidentified_data = {
            "00:00": {
                "end": "00:15",
                "name": "Reinforced Song"
            }
        }
        with open(self.run_dir / "unidentified.json", "w") as f:
            json.dump(unidentified_data, f)
            
        # 2. Run learn_songs.py (Mocking FFmpeg and Wav reading)
        # We want it to produce a specific fingerprint
        mock_fp = [0.1, 0.2, 0.3]
        
        # Patch BOTH learn_songs and label_marks_complete's DNAMatcher/SongMemoryManager
        with patch('subprocess.run'), \
             patch('scipy.io.wavfile.read', return_value=(16000, np.zeros(160000, dtype=np.int16))), \
             patch('audio_fingerprinter.compute_fingerprint', return_value=mock_fp), \
             patch('learn_songs.SongMemoryManager', lambda: SongMemoryManager(self.db_path)):
            
            learn_songs.learn_songs(self.test_vid)
            
        # Verify it's in the DB
        manager = SongMemoryManager(self.db_path)
        sigs = manager.get_all_signatures()
        # Ensure we have what we expect
        self.assertTrue(len(sigs) > 0, "No signatures found in DB after learning")
        self.assertTrue(any(name == "Reinforced Song" for name, fp in sigs))
        
        # 3. Identify it using label_marks_complete (Mocking Shazam failure)
        shazam_mock = AsyncMock()
        shazam_en_mock = AsyncMock()
        shazam_mock.recognize.return_value = None
        shazam_en_mock.recognize.return_value = None
        
        # We must also patch DNAMatcher in label_marks_complete to use our test DB
        test_matcher = label_marks_complete.DNAMatcher(self.db_path)
        
        with patch('label_marks_complete.dna_matcher', test_matcher), \
             patch('subprocess.run'), \
             patch('scipy.io.wavfile.read', return_value=(16000, np.zeros(160000, dtype=np.int16))), \
             patch('audio_fingerprinter.compute_fingerprint', return_value=mock_fp), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.stat') as mock_stat, \
             patch('pathlib.Path.unlink'):
            
            mock_stat.return_value.st_size = 2000
            
            result = await label_marks_complete.identify_song(
                shazam_mock, shazam_en_mock, self.audio_path, 0, 15.0, self.run_dir / "snippets"
            )
            
            self.assertEqual(result, "Reinforced Song")

if __name__ == '__main__':
    unittest.main()
