# Implementation Plan - Stabilize and Optimize Song Recognition Pipeline

## Phase 1: Robust Audio Acquisition
- [x] Task: Implement unit tests for `ensure_audio` duration validation.
- [x] Task: Refactor `ensure_audio` to strictly use YouTube duration vs local duration for all files (existing and new).
- [x] Task: Conductor - User Manual Verification 'Phase 1: Robust Audio Acquisition' (Protocol in workflow.md) [checkpoint: 910e4a0]

## Phase 2: Processing Loop Resilience
- [x] Task: Write tests for the marker selection logic (Processing... vs Unidentified).
- [x] Task: Update core loop to prevent infinite retries by explicitly saving "Unidentified" status on failure.
- [x] Task: Conductor - User Manual Verification 'Phase 2: Processing Loop Resilience' (Protocol in workflow.md) [checkpoint: 47d4797]

## Phase 3: Song Naming & Localization
- [x] Task: Create tests for `format_song_entry` covering Japanese mapping and long artist names.
- [x] Task: Refine `format_song_entry` to consistently apply the 60-character artist limit and custom mappings.
- [x] Task: Conductor - User Manual Verification 'Phase 3: Song Naming & Localization' (Protocol in workflow.md) *

## Phase 4: Signal Optimization
- [ ] Task: Standardize FFmpeg filters (`loudnorm`, `soxr`, `lowpass`) across all recognition attempts.
- [ ] Task: Verify signal quality using a sample test track.
- [ ] Task: Conductor - User Manual Verification 'Phase 4: Signal Optimization' (Protocol in workflow.md)
