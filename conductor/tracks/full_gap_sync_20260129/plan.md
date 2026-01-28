# Implementation Plan - Comprehensive Full-Gap Identification & Learning

## Phase 1: Shared Utility Update
- [ ] Task: Update `shared_utils.get_optimal_sliding_windows` logic.
    - [ ] Remove the `if gap_size > WINDOW_DURATION + 2.0` restriction.
    - [ ] Add logic to append `(0.0, gap_size)` as the final window only if `gap_size > WINDOW_DURATION`.
- [ ] Task: Update `tests/test_shared_utils.py` to verify the new window generation behavior.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Shared Utility Update' (Protocol in workflow.md)

## Phase 2: Verification across Modules
- [ ] Task: Verify `label_marks_complete.py` correctly handles the updated window list in both Shazam and Local DB phases.
- [ ] Task: Verify `learn_songs.py` correctly processes and stores the final full-gap signature.
- [ ] Task: Run an integration test `tests/test_full_gap_pipeline.py` to ensure a 12s gap results in exactly 3 windows (linear center-out) + 1 final full-gap window.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Verification across Modules' (Protocol in workflow.md)
