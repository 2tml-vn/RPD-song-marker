import asyncio
import os
from shazamio import Shazam, Serialize
from pydub import AudioSegment

async def main():
    shazam = Shazam()
    input_file = "runs/C_omZX8X_-A/audio.m4a"
    output_snippet = "debug_snippet.wav"

    print(f"Processing {input_file}...")

    # 1. Extract and Convert (Mimic label_marks_complete.py)
    try:
        # Load 10 seconds from 05:00
        start_ms = 5 * 60 * 1000
        end_ms = start_ms + (10 * 1000)
        
        print("Loading audio segment...")
        audio = AudioSegment.from_file(input_file)
        snippet = audio[start_ms:end_ms]
        
        print("Converting to 16kHz Mono WAV...")
        snippet = snippet.set_frame_rate(16000).set_channels(1)
        snippet.export(output_snippet, format="wav")
        
        print(f"Snippet saved to {output_snippet}")
        
        # Verify file size
        size = os.path.getsize(output_snippet)
        print(f"Snippet size: {size} bytes")
        
    except Exception as e:
        print(f"Error preparing audio: {e}")
        return

    # 2. Recognize
    try:
        print("Sending to Shazam...")
        # Read the file bytes manually to be sure
        with open(output_snippet, 'rb') as f:
            data = f.read()
            
        out = await shazam.recognize_song(data)
        print("--- SHAZAM RESPONSE ---")
        print(out)
        print("-----------------------")
        
        if len(out.get('matches', [])) == 0:
            print("RESULT: No Matches Found.")
        else:
            print("RESULT: Match Found!")
            track = out['track']
            print(f"Title: {track.get('title')}")
            print(f"Subtitle: {track.get('subtitle')}")
            
    except Exception as e:
        print(f"Error during recognition: {e}")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
