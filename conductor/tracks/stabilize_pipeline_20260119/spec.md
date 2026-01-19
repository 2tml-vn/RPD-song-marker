# Track Specification - Stabilize and Optimize Song Recognition Pipeline

## Overview
This track focuses on hardening the core Python processing loop and the audio acquisition pipeline to ensure high reliability and accuracy. The goal is to address existing pain points around truncated downloads, identification loops, and naming inconsistencies.

## Objectives
- **Zero-Truncation Policy:** Implement a definitive duration-based check to ensure audio files are complete before processing.
- **Robust Error Handling:** Ensure the script never enters infinite loops on failed identifications.
- **Optimized Matching:** Standardize FFmpeg parameters (normalization, resampling, filtering) to maximize Shazam's recognition success rate.
- **Consistent Japanese Localization:** Refine the mapping system and artist filtering to produce clean, localized tracklists.

## Scope
- Refactoring `label_marks_complete.py`.
- Improving `ensure_audio` validation logic.
- Standardizing `format_song_entry` logic.
- Enhancing the core `while` loop processing markers.

## Success Criteria
- The script successfully detects and redownloads truncated files using duration comparison.
- Failed identifications are explicitly marked as "Unidentified" and skipped in subsequent processing loops.
- Song titles correctly follow the mapping list and artist name length limits.
- FFmpeg output is optimized for 16kHz mono PCM with loudness normalization.
