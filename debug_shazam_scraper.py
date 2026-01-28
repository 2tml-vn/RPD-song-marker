import asyncio
import os
import time
from shazamio import Shazam
from shazamio.converter import Converter
from pydub import AudioSegment

async def main():
    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    audio_path = "runs/C_omZX8X_-A/audio_high.m4a"
    
    print(f"Loading high-quality audio...")
    audio = AudioSegment.from_file(audio_path)
    
    # 0:57 is the mark. We'll check from 0:57 to 1:27 (30 seconds)
    # But we'll check EVERY SECOND with a 4-second window.
    # This simulates how the real app works.
    
    start_sec = 57
    duration_to_scan = 30
    
    print(f"--- Deep Overlap Scan (1s steps) ---")
    for i in range(duration_to_scan):
        current_offset = start_sec + i
        
        # Take 4 seconds of audio (Shazam signatures usually represent ~3.1s)
        clip = audio[current_offset*1000 : (current_offset+4)*1000]
        
        # Format for Shazam
        norm_clip = Converter.normalize_audio_data(clip)
        
        # Generate signature
        # We manually create the generator to ensure it doesn't skip
        from shazamio.algorithm import SignatureGenerator
        sig_gen = SignatureGenerator()
        sig_gen.feed_input(norm_clip.get_array_of_samples())
        sig = sig_gen.get_next_signature()
        
        if sig:
            print(f"[{i+1}/{duration_to_scan}] Testing {current_offset}s...", end=" ", flush=True)
            try:
                # Use the low-level request sender
                out = await shazam.send_recognize_request(sig)
                if out and 'track' in out:
                    print(f"MATCH FOUND! -> {out['track']['title']}")
                    return
                else:
                    print("no match.")
            except Exception as e:
                print(f"error: {e}")
        
        # Rate limit safety
        await asyncio.sleep(0.2)

if __name__ == "__main__":
    asyncio.run(main())