import asyncio
from shazamio import Shazam

async def main():
    shazam = Shazam(language='ja-JP', endpoint_country='JP')
    out = await shazam.recognize('sanity_long.wav')
    print(out)

if __name__ == "__main__":
    asyncio.run(main())
