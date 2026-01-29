import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
import sys
import os

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import label_marks_complete
import shared_utils

async def verify_fix():
    video_id = "Q-3UGV0peAQ"
    # Target 10:27 which had a false positive before
    target_ts = "10:27"
    next_ts = "11:24"
    gap = shared_utils.parse_ts(next_ts) - shared_utils.parse_ts(target_ts)
    
    print(f"Verifying fix for {video_id} at {target_ts} (Gap: {gap}s)")
    
    # Mock dependencies
    shazam_mock = AsyncMock()
    shazam_en_mock = AsyncMock()
    shazam_mock.recognize.return_value = None # Shazam fails
    shazam_en_mock.recognize.return_value = None
    
    video_dir = Path("runs") / video_id
    audio_path = video_dir / "audio.m4a"
    snippets_dir = video_dir / "snippets"
    
    result = await label_marks_complete.identify_song(
        shazam_mock, shazam_en_mock, audio_path, shared_utils.parse_ts(target_ts), gap, snippets_dir
    )
    
    print(f"Result: {result}")
    
    if result == "Unidentified":
        print("SUCCESS: False positive eliminated.")
    else:
        print(f"FAILURE: Still matched as {result}")

if __name__ == "__main__":
    asyncio.run(verify_fix())
