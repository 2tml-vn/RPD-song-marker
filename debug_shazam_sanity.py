import asyncio
import os
import subprocess
from shazamio import Shazam

async def main():
    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    audio_path = "runs/C_omZX8X_-A/audio.m4a"
    
    # 27:49 is a known match
    start_sec = (27 * 60) + 49
    tmp_wav = "sanity_check_simple.wav"
    
    # CUT THE FILE EXACTLY AS THE MAIN SCRIPT DOES
    cmd = [
        "ffmpeg", "-y", "-ss", str(start_sec), "-t", "12", "-i", audio_path,
        "-vn", "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
        "-f", "wav", "-loglevel", "error", tmp_wav
    ]
    subprocess.run(cmd, check=True)
    
    print(f"Testing known match at 27:49 using standard high-level API...")
    out = await shazam.recognize(tmp_wav)
    
    if out and 'track' in out:
        print(f"  SUCCESS! Match: {out['track']['title']}")
    else:
        print(f"  FAILURE. No match even with standard method.")
        print(out)

    if os.path.exists(tmp_wav): os.remove(tmp_wav)

if __name__ == "__main__":
    asyncio.run(main())