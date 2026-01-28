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
from song_memory_manager import SongMemoryManager

class TestVariantRecognition(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.test_vid = "test_video_variant"
        self.run_dir = Path("runs") / self.test_vid
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = "test_variant_memory.db"
        if os.path.exists(self.db_path): os.remove(self.db_path)
        
        # Create a dummy audio file
        self.audio_path = self.run_dir / "audio.m4a"
        with open(self.audio_path, "wb") as f: f.write(b"dummy audio content")

    def tearDown(self):
        if self.run_dir.exists(): shutil.rmtree(self.run_dir)
        if os.path.exists(self.db_path): os.remove(self.db_path)

    async def test_multi_signature_recognition(self):
        # Mock pydub to avoid loading the dummy file
        with patch('learn_songs.AudioSegment.from_file'):
            # 1. Learn Version A as "Multi Song"
            unidentified_data_a = {
                "00:00": {
                    "end": "00:10",
                    "name": "Multi Song"
                }
            }
            with open(self.run_dir / "unidentified.json", "w") as f:
                json.dump(unidentified_data_a, f)
                
            mock_fp_a = [0.1] * 64
            
            # We must re-touch the audio file because learn_songs deletes it
            self.audio_path.touch()
            
            with patch('subprocess.run'), \
                 patch('scipy.io.wavfile.read', return_value=(16000, np.zeros(160000, dtype=np.int16))), \
                 patch('learn_songs.compute_fingerprint', return_value=mock_fp_a), \
                 patch('learn_songs.SongMemoryManager', lambda: SongMemoryManager(self.db_path)):
                
                learn_songs.learn_songs(self.test_vid)

            # 2. Learn Version B as "Multi Song" (Same name, different DNA)
            unidentified_data_b = {
                "00:10": {
                    "end": "00:20",
                    "name": "Multi Song"
                }
            }
            with open(self.run_dir / "unidentified.json", "w") as f:
                json.dump(unidentified_data_b, f)
                
            mock_fp_b = [0.9] * 64 # Very different from fp_a
            
            # RE-TOUCH!
            self.audio_path.touch()
            
            with patch('subprocess.run'), \
                 patch('scipy.io.wavfile.read', return_value=(16000, np.zeros(160000, dtype=np.int16))), \
                 patch('learn_songs.compute_fingerprint', return_value=mock_fp_b), \
                 patch('learn_songs.SongMemoryManager', lambda: SongMemoryManager(self.db_path)):
                
                learn_songs.learn_songs(self.test_vid)

            # 3. Verify Database Integrity
            manager = SongMemoryManager(self.db_path)
            songs = manager.get_all_songs()
            sigs = manager.get_all_signatures()
            
            self.assertEqual(len(songs), 1, "Should only have ONE song entry for 'Multi Song'")
            self.assertEqual(songs[0]['name'], "Multi Song")
            
            # Check that we have signatures close to both mock fingerprints
            print(f"DEBUG: Found {len(sigs)} signatures")
            for name, fp in sigs:
                print(f"  Song: {name}, FP Start: {fp[:3]}...")
            
            has_a = any(np.allclose(fp, mock_fp_a) for name, fp in sigs)
            has_b = any(np.allclose(fp, mock_fp_b) for name, fp in sigs)
            self.assertTrue(has_a, "Should contain signatures from Version A")
            self.assertTrue(has_b, "Should contain signatures from Version B")

            # 4. Identify a clip of Version B
            shazam_mock = AsyncMock()
            shazam_en_mock = AsyncMock()
            shazam_mock.recognize.return_value = None # Shazam fails
            shazam_en_mock.recognize.return_value = None
            
            # Patch DNAMatcher in label_marks_complete to use our test DB
            test_matcher = label_marks_complete.DNAMatcher(self.db_path)
            
            # RE-TOUCH again for identification
            self.audio_path.touch()
            
            with patch('label_marks_complete.dna_matcher', test_matcher), \
                 patch('subprocess.run'), \
                 patch('scipy.io.wavfile.read', return_value=(16000, np.zeros(160000, dtype=np.int16))), \
                 patch('label_marks_complete.compute_fingerprint', return_value=mock_fp_b), \
                 patch('pathlib.Path.exists', return_value=True), \
                 patch('pathlib.Path.stat') as mock_stat, \
                 patch('pathlib.Path.unlink'):
                
                mock_stat.return_value.st_size = 2000
                
                result = await label_marks_complete.identify_song(
                    shazam_mock, shazam_en_mock, self.audio_path, 10, 10.0, self.run_dir / "snippets"
                )
                
                self.assertEqual(result, "Multi Song", "Should identify Version B clip as 'Multi Song'")

if __name__ == '__main__':
    unittest.main()
