import asyncio
import os
from shazamio import Shazam
from pydub import AudioSegment

async def test_mark(shazam, audio_path, start_sec, desc):
    print(f"Testing {desc}...")
    try:
        audio = AudioSegment.from_file(audio_path)
        start_ms = start_sec * 1000
        end_ms = start_ms + 12000
        clip = audio[start_ms:end_ms]
        
        # recognize_song uses the algorithm.py logic I just fixed
        out = await shazam.recognize_song(clip)
        if out and 'track' in out:
            print(f"  MATCH: {out['track']['title']}")
        else:
            print(f"  NO MATCH.")
    except Exception as e:
        print(f"  Error: {e}")

async def main():
    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    audio = "runs/C_omZX8X_-A/audio_high.m4a"
    
    print("--- TESTING RECOGNIZE_SONG (WITH LIB FIX) ---")
    await test_mark(shazam, audio, 57, "Control at 0:57")
    await test_mark(shazam, audio, 93, "Target at 1:33")

if __name__ == "__main__":
    asyncio.run(main())
