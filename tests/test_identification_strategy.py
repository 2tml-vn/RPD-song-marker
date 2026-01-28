import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
from pathlib import Path
import time

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import label_marks_complete
import shared_utils

class TestIdentificationStrategy(unittest.IsolatedAsyncioTestCase):

    async def test_shazam_all_then_local_all(self):
        # Setup mocks
        shazam_mock = AsyncMock()
        shazam_en_mock = AsyncMock()
        dna_matcher_mock = MagicMock()
        
        # We need to mock label_marks_complete.dna_matcher
        with patch('label_marks_complete.dna_matcher', dna_matcher_mock), \
             patch('label_marks_complete.shared_utils.get_optimal_sliding_windows') as mock_get_windows, \
             patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.stat') as mock_stat, \
             patch('pathlib.Path.unlink'), \
             patch('scipy.io.wavfile.read', return_value=(16000, MagicMock())), \
             patch('audio_fingerprinter.compute_fingerprint', return_value=MagicMock()):

            mock_stat.return_value.st_size = 2000
            
            # 2 windows for testing
            mock_get_windows.return_value = [(0.0, 10.0), (5.0, 10.0)]
            
            # Scenario: Shazam fails for all, Local matches on 2nd window
            shazam_mock.recognize.return_value = None
            shazam_en_mock.recognize.return_value = None
            
            # dna_matcher.find_match(fp)
            # 1st call: None
            # 2nd call: "Local Song", 0.95
            dna_matcher_mock.find_match.side_effect = [(None, 0.0), ("Local Song", 0.95)]
            
            result = await label_marks_complete.identify_song(
                shazam_mock, shazam_en_mock, "mock_audio.m4a", 0, 15.0, Path("mock_snippets")
            )
            
            self.assertEqual(result, "Local Song")
            
            # Verify attempts:
            # Phase 1: Shazam windows 1 and 2
            self.assertEqual(shazam_mock.recognize.call_count, 2)
            self.assertEqual(shazam_en_mock.recognize.call_count, 2)
            
            # Phase 2: Local windows 1 and 2
            self.assertEqual(dna_matcher_mock.find_match.call_count, 2)

    async def test_shazam_match_immediate_return(self):
        # Setup mocks
        shazam_mock = AsyncMock()
        shazam_en_mock = AsyncMock()
        dna_matcher_mock = MagicMock()
        
        with patch('label_marks_complete.dna_matcher', dna_matcher_mock), \
             patch('label_marks_complete.shared_utils.get_optimal_sliding_windows') as mock_get_windows, \
             patch('subprocess.run') as mock_run, \
             patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.stat') as mock_stat, \
             patch('pathlib.Path.unlink'):

            mock_stat.return_value.st_size = 2000
            mock_get_windows.return_value = [(0.0, 10.0), (5.0, 10.0)]
            
            # Shazam matches on 1st window
            shazam_mock.recognize.return_value = {
                'track': {'title': 'Shazam Song', 'subtitle': 'Artist', 'key': '123'}
            }
            # Mock track_about to avoid actual network call
            shazam_en_mock.track_about = AsyncMock(return_value={})
            
            result = await label_marks_complete.identify_song(
                shazam_mock, shazam_en_mock, "mock_audio.m4a", 0, 15.0, Path("mock_snippets")
            )
            
            self.assertEqual(result, "Shazam Song - Artist")
            
            # Shazam should only be called once
            self.assertEqual(shazam_mock.recognize.call_count, 1)
            # DNA Matcher should NOT be called at all
            self.assertEqual(dna_matcher_mock.find_match.call_count, 0)

if __name__ == '__main__':
    unittest.main()
