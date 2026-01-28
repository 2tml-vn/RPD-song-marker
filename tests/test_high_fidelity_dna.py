import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
from pathlib import Path
import json
import numpy as np
import os
import shutil

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import learn_songs
import label_marks_complete
import shared_utils
from song_memory_manager import SongMemoryManager

class TestHighFidelityDNA(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.test_vid = "test_video_hifi"
        self.run_dir = Path("runs") / self.test_vid
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = "test_hifi_memory.db"
        if os.path.exists(self.db_path): os.remove(self.db_path)
        
        self.audio_path = self.run_dir / "audio.m4a"
        with open(self.audio_path, "wb") as f: f.write(b"dummy audio content")

    def tearDown(self):
        if self.run_dir.exists(): shutil.rmtree(self.run_dir)
        if os.path.exists(self.db_path): os.remove(self.db_path)

    async def test_end_to_end_hifi(self):
        # 1. Setup unidentified.json
        unidentified_data = {
            "00:00": {
                "end": "00:10",
                "name": "HiFi Song"
            }
        }
        with open(self.run_dir / "unidentified.json", "w") as f:
            json.dump(unidentified_data, f)

        # 2. Learn the song
        # Mock FFmpeg and Wav read to return a "richer" fake signal (sine + noise)
        sr = 16000
        y = np.sin(2 * np.pi * 440 * np.linspace(0, 10, sr * 10))
        
        with patch('learn_songs.AudioSegment.from_file'), \
             patch('subprocess.run'), \
             patch('scipy.io.wavfile.read', return_value=(sr, (y * 32767).astype(np.int16))), \
             patch('learn_songs.SongMemoryManager', lambda: SongMemoryManager(self.db_path)):
            
            learn_songs.learn_songs(self.test_vid)

        # 3. Verify signatures in DB
        manager = SongMemoryManager(self.db_path)
        sigs = manager.get_all_signatures()
        self.assertGreater(len(sigs), 0)
        self.assertEqual(len(sigs[0][1]), 26, "DNA should be 26 dimensions (13 mean + 13 std)")

        # 4. Identify it
        shazam_mock = AsyncMock()
        shazam_en_mock = AsyncMock()
        shazam_mock.recognize.return_value = None
        shazam_en_mock.recognize.return_value = None
        
        test_matcher = label_marks_complete.DNAMatcher(self.db_path)
        
        # Ensure snippets folder exists
        (self.run_dir / "snippets").mkdir(exist_ok=True)
        self.audio_path.touch()

        with patch('label_marks_complete.dna_matcher', test_matcher), \
             patch('subprocess.run'), \
             patch('scipy.io.wavfile.read', return_value=(sr, (y * 32767).astype(np.int16))), \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.stat') as mock_stat, \
             patch('pathlib.Path.unlink'):
            
            mock_stat.return_value.st_size = 2000
            
            # Use identify_song directly
            result = await label_marks_complete.identify_song(
                shazam_mock, shazam_en_mock, self.audio_path, 0, 10.0, self.run_dir / "snippets"
            )
            
            self.assertEqual(result, "HiFi Song")

if __name__ == '__main__':
    unittest.main()
