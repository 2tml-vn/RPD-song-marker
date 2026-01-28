# Implementation Plan - Persistent Audio for Learning

## Phase 1: Conditional Deletion in Main Pipeline
- [x] Task: Update `label_marks_complete.py` to check for unidentified songs before cleanup.
    - [x] Modify the `[FINISH]` logic to verify if `unidentified_data` is non-empty.
    - [x] Wrap the `audio_path.unlink()` call in a conditional block that only executes if no unidentified songs exist.
    - [x] Add a logger message informing the user when the audio is preserved for learning.
- [x] Task: Write a test to verify the conditional deletion logic.
    - [x] Mock the file system and identification results.
    - [x] Assert that `unlink` is called when results are 100% identified.
    - [x] Assert that `unlink` is NOT called when "Unidentified" results are present.
- [x] Task: Conductor - User Manual Verification 'Phase 1: Conditional Deletion in Main Pipeline' (Protocol in workflow.md)

## Phase 2: Automated Cleanup in Learner
- [x] Task: Update `learn_songs.py` to handle audio cleanup.
    - [x] Add logic at the end of the `learn_songs` function to delete the `audio_path` after the `SongMemoryManager` has successfully added all signatures.
    - [x] Ensure cleanup only happens if `learned_count > 0` or if the user has explicitly finished providing names.
- [x] Task: Write a test for `learn_songs.py` cleanup.
    - [x] Mock a successful learning run.
    - [x] Verify the audio file is deleted post-run.
- [x] Task: Conductor - User Manual Verification 'Phase 2: Automated Cleanup in Learner' (Protocol in workflow.md)

## Phase 3: End-to-End Integration Test
- [x] Task: Create a script to simulate the full workflow.
    - [x] Run a mock marking session that results in "Unidentified".
    - [x] Verify audio exists.
    - [x] Run `learn_songs.py`.
    - [x] Verify audio is gone.
- [x] Task: Conductor - User Manual Verification 'Phase 3: End-to-End Integration Test' (Protocol in workflow.md)
