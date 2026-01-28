import asyncio
import os
import subprocess
from shazamio import Shazam
from shazamio.converter import Converter
from pydub import AudioSegment

async def main():
    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    audio_path = "runs/C_omZX8X_-A/audio_high.m4a"
    
    # We'll try different pitch shifts at the 1:05 mark
    start_sec = 65
    
    # Shift factors: 1.0 (orig), 0.95 (down 5%), 0.90 (down 10%), 1.05 (up 5%)
    shifts = [1.0, 0.95, 0.92, 1.05]
    
    print(f"--- Pitch Shift Resilience Test (at {start_sec}s) ---")
    
    for s in shifts:
        tmp_wav = f"debug_pitch_{s}.wav"
        print(f"Testing pitch shift {s}x...", end=" ", flush=True)
        
        # asetrate shifts both pitch and speed (vinyl style)
        # then atempo corrects the speed back to 1.0
        # Actually, if the DJ just sped it up, we only need to correct the rate.
        rate = int(44100 * (1/s))
        cmd = [
            "ffmpeg", "-y", "-ss", str(start_sec), "-t", "4", "-i", audio_path,
            "-af", f"asetrate={rate},atempo={s}", 
            "-ar", "16000", "-ac", "1", tmp_wav, "-loglevel", "error"
        ]
        subprocess.run(cmd, check=True)
        
        try:
            out = await shazam.recognize(tmp_wav)
            if out and 'track' in out:
                print(f"MATCH! -> {out['track']['title']}")
                return
            else:
                print("no match.")
        except:
            print("error.")
        finally:
            if os.path.exists(tmp_wav): os.remove(tmp_wav)

if __name__ == "__main__":
    asyncio.run(main())
