import asyncio
import os
from shazamio import Shazam

async def main():
    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    path = "sanity_debug.wav"
    
    print(f"--- Final Diagnostic: Testing high-level methods on known clip ---")
    
    # Method 1: The standard recognize (modern)
    print("Testing recognize()...", end=" ", flush=True)
    out1 = await shazam.recognize(path)
    if out1 and 'track' in out1:
        print(f"SUCCESS! -> {out1['track']['title']}")
    else:
        print("fail.")

    # Method 2: The deprecated recognize_song (legacy)
    print("Testing recognize_song()...", end=" ", flush=True)
    out2 = await shazam.recognize_song(path)
    if out2 and 'track' in out2:
        print(f"SUCCESS! -> {out2['track']['title']}")
    else:
        print("fail.")

if __name__ == "__main__":
    asyncio.run(main())
