# Technology Stack - JRPD Live Marker Pro

## Primary Technologies
- **Python (3.10+):** The core backend language, utilized for its robust asynchronous support and extensive library ecosystem.
- **JavaScript/TypeScript:** Used for the frontend userscript and the Jumpcutter extension components.
- **FFmpeg:** The primary engine for audio extraction, duration validation, and signal processing.

## Backend Dependencies
- **ShazamIO:** Asynchronous Python library for interfacing with the reverse-engineered Shazam API.
- **yt-dlp:** Advanced command-line tool for video and audio acquisition, configured with mobile client spoofing for high resilience.
- **pydub & numpy:** Utilized for audio manipulation and mathematical signal transformations.
- **scipy:** Used for advanced mathematical signal transformations and processing in conjunction with FFmpeg.
- **asyncio & aiohttp:** Foundation for non-blocking I/O and network requests.

## Frontend & Client Architecture
- **Tampermonkey Userscript:** Provides the primary marking UI directly injected into the YouTube player.
- **Svelte:** UI framework utilized for advanced extension features (within the Jumpcutter codebase).
- **CSS3 (Modern Styles):** Implementing glassmorphism, flexbox layout, and hardware-accelerated animations for a polished UX.

## Communication & State
- **HTTP Bridge:** A local Python-based HTTP server facilitating real-time marker data transfer from the browser to the backend.
- **JSON:** The standard for project state, progress tracking, and metadata storage.
