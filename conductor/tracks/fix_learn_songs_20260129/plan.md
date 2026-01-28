# Implementation Plan - Fix learn_songs.py and Dependency Mismatch

## Phase 1: Fix Critical Errors and Dependencies
- [ ] Task: Create `requirements.txt` with standardized dependencies.
    - [ ] Pin `numpy>=1.23.5,<2.3.0` to resolve SciPy warning.
    - [ ] Add `scipy`, `pydub`, `shazamio`, `yt-dlp`, `aiohttp`, `numpy`.
- [ ] Task: Fix `learn_songs.py` missing import.
    - [ ] Write a failing test that attempts to run the `learn_songs` initialization.
    - [ ] Add `from pydub import AudioSegment` to `learn_songs.py`.
    - [ ] Verify the test passes and the `NameError` is resolved.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Fix Critical Errors and Dependencies' (Protocol in workflow.md)

## Phase 2: Import Audit and Script Standardization
- [ ] Task: Audit `audio_fingerprinter.py` for correct imports and dependencies.
- [ ] Task: Audit `label_marks_complete.py` for correct imports and dependencies.
- [ ] Task: Audit `dna_matcher.py` for correct imports and dependencies.
- [ ] Task: Audit `audio_dna.py` for correct imports and dependencies.
- [ ] Task: Verify all core scripts pass a basic syntax and import check using `python -m py_compile`.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Import Audit and Script Standardization' (Protocol in workflow.md)

## Phase 3: Final Verification
- [ ] Task: Run a sample learning session with `learn_songs.py` on a known `video_id`.
- [ ] Task: Confirm the NumPy version warning is gone from the console output.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Final Verification' (Protocol in workflow.md)
