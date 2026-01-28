# Track Specification - Persistent Audio for Learning

## Overview
Improve the "Identity Learning" workflow by preventing the premature deletion of audio files. Currently, `label_marks_complete.py` deletes the audio file immediately upon finishing, which prevents `learn_songs.py` from functioning. This track ensures audio is preserved when needed and cleaned up only after learning is complete.

## Functional Requirements
1.  **Conditional Deletion in Main Loop:** 
    - Update `label_marks_complete.py` to check for "Unidentified" results before deleting the audio file during the `[FINISH]` sequence.
    - If `unidentified.json` is created (meaning there are songs to learn), the audio file must be preserved.
    - If all songs were identified, the audio file should be deleted as usual to save space.
2.  **Automated Cleanup in Learner:**
    - Update `learn_songs.py` to delete the source audio file (`audio.m4a`, etc.) only after it has successfully processed all entries in `unidentified.json` and updated the local database.
3.  **Error Resilience:**
    - If `learn_songs.py` fails or is interrupted, the audio file should remain untouched so the user can retry.

## Acceptance Criteria
1.  Running `label_marks_complete.py` on a video with 100% identification results in the audio file being deleted.
2.  Running `label_marks_complete.py` on a video with "Unidentified" songs preserves the audio file in the `runs/<video_id>/` directory.
3.  Running `learn_songs.py <video_id>` successfully fingerprints the songs and then deletes the audio file.
4.  The `unidentified.json` file remains as a record, but the heavy audio file is removed after learning.

## Out of Scope
- Changing the fingerprinting algorithm itself.
- Batch processing multiple videos in one `learn_songs.py` call.
