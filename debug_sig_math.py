import asyncio
from shazamio import Shazam
from shazamio.converter import Converter
from pydub import AudioSegment

async def check_sig_duration(vid_id, start_sec):
    audio_path = f"runs/{vid_id}/audio.m4a"
    audio = AudioSegment.from_file(audio_path)
    start_ms = start_sec * 1000
    # Take a long slice, but the generator will truncate it
    clip = audio[start_ms : start_ms + 12000]
    
    norm_clip = Converter.normalize_audio_data(clip)
    sig_gen = Converter.create_signature_generator(norm_clip)
    sig = sig_gen.get_next_signature()
    
    # Calculate duration: number_samples / sample_rate
    duration = sig.number_samples / sig.sample_rate_hz
    peaks = sum(len(p) for p in sig.frequency_band_to_sound_peaks.values())
    
    return duration, peaks

async def main():
    vid = "C_omZX8X_-A"
    
    # 0:57 (Success)
    d1, p1 = await check_sig_duration(vid, 57)
    print(f"Success Segment (0:57): Duration={d1:.2f}s, Peaks={p1}")
    
    # 28:18 (Fail)
    d2, p2 = await check_sig_duration(vid, 1698)
    print(f"Failed Segment (28:18): Duration={d2:.2f}s, Peaks={p2}")

if __name__ == "__main__":
    asyncio.run(main())
