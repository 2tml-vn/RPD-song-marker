import unittest
import sys
import os
from pathlib import Path

# Add parent directory to path to import learn_songs
sys.path.append(str(Path(__file__).resolve().parent.parent))

class TestLearnSongsImport(unittest.TestCase):
    def test_import_and_init(self):
        # This will fail with NameError if AudioSegment is not defined
        import learn_songs
        # We don't even need to call anything, the module level code 
        # or the function definition might be enough if it was called.
        # But let's check if we can access AudioSegment in learn_songs.
        # Actually, the error was: "NameError: name 'AudioSegment' is not defined"
        # occurring at line 37 in learn_songs.py
        
        # We can try to trigger the function to reach line 37, 
        # but even a basic check of the globals in that module would work.
        self.assertTrue(hasattr(learn_songs, 'AudioSegment'), "AudioSegment not found in learn_songs.py")

if __name__ == '__main__':
    unittest.main()
