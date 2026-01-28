import asyncio
import os
from shazamio import Shazam
from pydub import AudioSegment

async def main():
    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    audio_path = "runs/C_omZX8X_-A/audio_high.m4a"
    
    # Take a 30 second clip instead of 12
    audio = AudioSegment.from_file(audio_path)
    start_ms = 57 * 1000
    end_ms = start_ms + (30 * 1000)
    clip = audio[start_ms:end_ms]
    
    print(f"Testing 30s clip starting at 0:57 (High Bitrate)...")
    out = await shazam.recognize_song(clip)
    
    if out and 'track' in out:
        print(f"  MATCH FOUND: {out['track']['title']}")
    else:
        print(f"  NO MATCH.")

if __name__ == "__main__":
    asyncio.run(main())
