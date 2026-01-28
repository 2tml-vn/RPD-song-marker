import asyncio
import os
from shazamio import Shazam
from pydub import AudioSegment

async def test_mark(shazam, audio_path, start_sec, desc):
    print(f"Testing {desc} at {start_sec}s...")
    try:
        audio = AudioSegment.from_file(audio_path)
        start_ms = start_sec * 1000
        end_ms = start_ms + 12000
        clip = audio[start_ms:end_ms]
        clip = clip.set_frame_rate(16000).set_channels(1)
        tmp_path = f"debug_offset_{start_sec}.wav"
        clip.export(tmp_path, format="wav")
        
        out = await shazam.recognize(tmp_path)
        if out and 'track' in out:
            print(f"  MATCH: {out['track']['title']}")
        else:
            print(f"  NO MATCH.")
        if os.path.exists(tmp_path): os.remove(tmp_path)
    except Exception as e:
        print(f"  Error: {e}")

async def main():
    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    audio = "runs/C_omZX8X_-A/audio.m4a"
    
    print("--- TESTING OFFSETS for 0:57 mark ---")
    await test_mark(shazam, audio, 57, "Exactly at mark (0:57)")
    await test_mark(shazam, audio, 67, "10s After mark (1:07)")
    await test_mark(shazam, audio, 77, "20s After mark (1:17)")

if __name__ == "__main__":
    asyncio.run(main())
