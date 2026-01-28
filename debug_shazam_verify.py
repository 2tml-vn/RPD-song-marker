import asyncio
import os
from shazamio import Shazam
from pydub import AudioSegment

async def test_mark(shazam, audio_path, start_sec, desc):
    print(f"Testing {desc}...")
    if not os.path.exists(audio_path):
        print(f"  Error: {audio_path} missing.")
        return
    
    # Cut with Pydub
    try:
        audio = AudioSegment.from_file(audio_path)
        start_ms = start_sec * 1000
        end_ms = start_ms + 12000
        clip = audio[start_ms:end_ms]
        
        # Apply standard Shazam format
        clip = clip.set_frame_rate(16000).set_channels(1)
        tmp_path = f"debug_tmp_{start_sec}.wav"
        clip.export(tmp_path, format="wav")
        
        # Recognize
        out = await shazam.recognize(tmp_path)
        if out and 'track' in out:
            print(f"  MATCH: {out['track']['title']} - {out['track']['subtitle']}")
        else:
            print(f"  NO MATCH. (Response: {out.get('matches', 'Error')})")
            
        if os.path.exists(tmp_path): os.remove(tmp_path)
    except Exception as e:
        print(f"  Error: {e}")

async def main():
    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    
    # 1. SUPER CONTROL (Normal video, should definitely work)
    await test_mark(shazam, "runs/kqlQEGNjprc/audio.m4a", 8, "Super Control (kqlQEGNjprc 8s)")
    
    # 2. CONTROL (Working song in problematic video)
    await test_mark(shazam, "runs/C_omZX8X_-A/audio.m4a", 57, "Working Control (C_omZX8X_-A 57s)")
    
    # 3. TARGET (Failed song in problematic video - Original)
    await test_mark(shazam, "runs/C_omZX8X_-A/audio.m4a", 93, "Target Fail (C_omZX8X_-A 1:33 original)")
    
    # 4. TARGET (Failed song in problematic video - High Bitrate)
    await test_mark(shazam, "runs/C_omZX8X_-A/audio_high.m4a", 93, "Target Fail (C_omZX8X_-A 1:33 high-bitrate)")

if __name__ == "__main__":
    asyncio.run(main())
