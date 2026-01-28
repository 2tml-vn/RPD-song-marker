# Track Specification - Fix learn_songs.py and Dependency Mismatch

## Overview
Address a critical `NameError` in `learn_songs.py` and resolve environment-level warnings regarding NumPy and SciPy compatibility. This track also includes a proactive audit of core scripts to ensure all dependencies are correctly imported.

## Functional Requirements
1.  **Fix `learn_songs.py` Import Error:**
    - Add `from pydub import AudioSegment` to the imports section.
    - Ensure `pydub` is correctly utilized for audio normalization.
2.  **Resolve Dependency Mismatch:**
    - Create a root `requirements.txt` file.
    - Pin `numpy` to a version compatible with the installed SciPy (e.g., `numpy>=1.23.5,<2.3.0`).
    - Include other primary dependencies: `pydub`, `scipy`, `shazamio`, `yt-dlp`, `aiohttp`, etc.
3.  **Core Script Import Audit:**
    - Audit `audio_fingerprinter.py`, `label_marks_complete.py`, `dna_matcher.py`, and `audio_dna.py` for missing imports or potential `NameError` bugs.
    - Standardize import styles across the project.

## Acceptance Criteria
1.  `python learn_songs.py <VIDEO_ID>` runs without `NameError: name 'AudioSegment' is not defined`.
2.  The `UserWarning` about NumPy version mismatch is no longer present when running scripts.
3.  A `requirements.txt` file exists in the root directory and contains all necessary dependencies for the project.
4.  All audited scripts run their basic initialization without immediate import errors.

## Out of Scope
- Major refactoring of the fingerprinting logic.
- Upgrading to Python 3.13 or other major environment shifts beyond fixing the current version conflicts.
