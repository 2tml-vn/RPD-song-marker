# Initial Concept
A tool to label and identify music tracks in YouTube videos by syncing browser markers with a Python backend.

# Product Guide - JRPD Live Marker Pro

## Vision
A seamless, semi-automated workflow for timestamping and identifying music tracks in YouTube videos. By bridging browser-based manual marking with a robust local Python backend, JRPD Live Marker Pro enables creators and viewers to generate accurate, formatted tracklists with minimal effort.

## Target Audience
- **Content Creators & Editors:** Streamlining the process of creating tracklists for long-form content, DJ mixes, or VODs.
- **Viewers & Music Enthusiasts:** Enabling users to identify songs in real-time while watching a video and save them for later.

## Core Features
- **Real-Time Browser Marking:** A lightweight userscript UI with keyboard shortcuts (like pressing 'A') to pin-point song transitions directly in the YouTube player. Includes a **Master Visibility Toggle** integrated into the YouTube control bar for zero-obstruction viewing while maintaining background marking functionality.
- **Variable Speed Compensation:** Intelligent timestamp calculation that accounts for playback speed adjustments (e.g., watching at 2x or using Jumpcutter) to ensure marker accuracy.
- **Automated Audio Pipeline:** Robust backend that handles video downloading, integrity validation (detecting truncated files), and high-precision audio cutting using FFmpeg.
- **AI-Powered Identification:** Integration with the reverse-engineered Shazam API (via ShazamIO) using a deterministic **Optimal Dynamic Sliding Window** strategy. This ensures 100% coverage of the song timeline by sliding 10-second search windows across the available gap using a "Center-Out" attempt order, concluding with a full-gap fallback attempt to maximize identification chances while bypassing transition noise.
- **Local Identity Learning:** A robust fallback system that learns the "Audio DNA" of unidentified songs. Users can manually identify tracks in an `unidentified.json` file, which the system then fingerprints and stores in a local database for automatic recognition in future sessions. Supports **Multi-Signature Reinforcement** and **Global Deduplication**, ensuring every unique fingerprint exists only once in the database to prevent bloat.
- **Symmetric Recognition:** Uses identical windowing logic for both learning and recognition, ensuring that local matching is timing-proof and resilient to transition noise.
- **Resilient Processing:** Advanced error handling including mobile client spoofing to bypass 403 Forbidden errors and automatic retries for failed identifications.
- **Database Correction Utility:** A safe JSON-based workflow for batch renaming songs in the local database, allowing users to correct or refine identified names without direct SQL manipulation.
- **Clean Export:** Generation of ready-to-use text files formatted for YouTube comments or descriptions.
- **Manual Review Fallback:** Automatic export of full-length audio segments for any tracks that could not be identified, allowing for easy manual verification.

## Workflow Goal
The project aims to provide the most convenient workflow possible, minimizing manual file management and allowing the user to focus on the content while the technical overhead of identification and formatting is handled automatically.
