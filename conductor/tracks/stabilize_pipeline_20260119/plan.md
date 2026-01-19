# Implementation Plan - Stabilize and Optimize Song Recognition Pipeline

## Phase 1: Robust Audio Acquisition
- [ ] Task: Implement unit tests for `ensure_audio` duration validation.
- [ ] Task: Refactor `ensure_audio` to strictly use YouTube duration vs local duration for all files (existing and new).
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Robust Audio Acquisition' (Protocol in workflow.md)

## Phase 2: Processing Loop Resilience
- [ ] Task: Write tests for the marker selection logic (Processing... vs Unidentified).
- [ ] Task: Update core loop to prevent infinite retries by explicitly saving "Unidentified" status on failure.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Processing Loop Resilience' (Protocol in workflow.md)

## Phase 3: Song Naming & Localization
- [ ] Task: Create tests for `format_song_entry` covering Japanese mapping and long artist names.
- [ ] Task: Refine `format_song_entry` to consistently apply the 60-character artist limit and custom mappings.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Song Naming & Localization' (Protocol in workflow.md)

## Phase 4: Signal Optimization
- [ ] Task: Standardize FFmpeg filters (`loudnorm`, `soxr`, `lowpass`) across all recognition attempts.
- [ ] Task: Verify signal quality using a sample test track.
- [ ] Task: Conductor - User Manual Verification 'Phase 4: Signal Optimization' (Protocol in workflow.md)
