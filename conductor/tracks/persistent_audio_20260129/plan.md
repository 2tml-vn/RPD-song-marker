# Implementation Plan - Persistent Audio for Learning

## Phase 1: Conditional Deletion in Main Pipeline
- [ ] Task: Update `label_marks_complete.py` to check for unidentified songs before cleanup.
    - [ ] Modify the `[FINISH]` logic to verify if `unidentified_data` is non-empty.
    - [ ] Wrap the `audio_path.unlink()` call in a conditional block that only executes if no unidentified songs exist.
    - [ ] Add a logger message informing the user when the audio is preserved for learning.
- [ ] Task: Write a test to verify the conditional deletion logic.
    - [ ] Mock the file system and identification results.
    - [ ] Assert that `unlink` is called when results are 100% identified.
    - [ ] Assert that `unlink` is NOT called when "Unidentified" results are present.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Conditional Deletion in Main Pipeline' (Protocol in workflow.md)

## Phase 2: Automated Cleanup in Learner
- [ ] Task: Update `learn_songs.py` to handle audio cleanup.
    - [ ] Add logic at the end of the `learn_songs` function to delete the `audio_path` after the `SongMemoryManager` has successfully added all signatures.
    - [ ] Ensure cleanup only happens if `learned_count > 0` or if the user has explicitly finished providing names.
- [ ] Task: Write a test for `learn_songs.py` cleanup.
    - [ ] Mock a successful learning run.
    - [ ] Verify the audio file is deleted post-run.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Automated Cleanup in Learner' (Protocol in workflow.md)

## Phase 3: End-to-End Integration Test
- [ ] Task: Create a script to simulate the full workflow.
    - [ ] Run a mock marking session that results in "Unidentified".
    - [ ] Verify audio exists.
    - [ ] Run `learn_songs.py`.
    - [ ] Verify audio is gone.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: End-to-End Integration Test' (Protocol in workflow.md)
