# Initial Concept
A tool to label and identify music tracks in YouTube videos by syncing browser markers with a Python backend.

# Product Guide - JRPD Live Marker Pro

## Vision
A seamless, semi-automated workflow for timestamping and identifying music tracks in YouTube videos. By bridging browser-based manual marking with a robust local Python backend, JRPD Live Marker Pro enables creators and viewers to generate accurate, formatted tracklists with minimal effort.

## Target Audience
- **Content Creators & Editors:** Streamlining the process of creating tracklists for long-form content, DJ mixes, or VODs.
- **Viewers & Music Enthusiasts:** Enabling users to identify songs in real-time while watching a video and save them for later.

## Core Features
- **Real-Time Browser Marking:** A lightweight userscript UI with keyboard shortcuts (like pressing 'A') to pin-point song transitions directly in the YouTube player.
- **Variable Speed Compensation:** Intelligent timestamp calculation that accounts for playback speed adjustments (e.g., watching at 2x or using Jumpcutter) to ensure marker accuracy.
- **Automated Audio Pipeline:** Robust backend that handles video downloading, integrity validation (detecting truncated files), and high-precision audio cutting using FFmpeg.
- **AI-Powered Identification:** Integration with the reverse-engineered Shazam API (via ShazamIO) to identify tracks, with a specific focus on high-quality Japanese localization support.
- **Resilient Processing:** Advanced error handling including mobile client spoofing to bypass 403 Forbidden errors and automatic retries for failed identifications.
- **Clean Export:** Generation of ready-to-use text files formatted for YouTube comments or descriptions.
- **Manual Review Fallback:** Automatic export of full-length audio segments for any tracks that could not be identified, allowing for easy manual verification.

## Workflow Goal
The project aims to provide the most convenient workflow possible, minimizing manual file management and allowing the user to focus on the content while the technical overhead of identification and formatting is handled automatically.
