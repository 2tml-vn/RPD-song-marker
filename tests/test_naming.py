import unittest
import sys
from pathlib import Path

# Add parent directory to path to import the script
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Mock Shazam to avoid side effects on import
from unittest.mock import patch
with patch('shazamio.Shazam'):
    from label_marks_complete import format_song_entry

class TestSongNaming(unittest.TestCase):

    def test_japanese_mapping(self):
        # Setup input
        song_info = "nightcord - deaya"
        expected = "キャットラビング - 25時、ナイトコードで。"
        self.assertEqual(format_song_entry(song_info), expected)
        
        song_info = "deaya - nightcord"
        self.assertEqual(format_song_entry(song_info), expected)

    def test_long_artist_filtering(self):
        # Setup input with very long artist name (> 60 chars)
        title = "うまぴょい伝説"
        long_artist = "スペシャルウィーク (CV 和氣あず未), サイレンススズカ (CV 高野麻里佳), トウカイテイオー (CV Machico), マルゼンスキー (CV Lynn), オグリキャップ (CV 高柳知葉), ゴールドシップ (CV 上田 瞳)"
        song_info = f"{title} - {long_artist}"
        
        # It should return only the title
        self.assertEqual(format_song_entry(song_info), title)

    def test_standard_formatting(self):
        # Setup standard input
        song_info = "Song Title (Official Video) - Artist Name"
        expected = "Song Title - Artist Name"
        self.assertEqual(format_song_entry(song_info), expected)

if __name__ == '__main__':
    unittest.main()
