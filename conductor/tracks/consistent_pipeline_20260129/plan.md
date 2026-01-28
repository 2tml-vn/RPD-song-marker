# Implementation Plan - Consistent Identification Pipeline

## Phase 1: Core Utility Standardization
- [ ] Task: Update `shared_utils.py` to be the source of truth for `WINDOW_DURATION` (10.0), `parse_ts`, `format_song_entry`, and `get_optimal_sliding_windows`.
- [ ] Task: Implement unit tests in `tests/test_shared_utils.py` to verify the "Center-Out" strategy and `format_song_entry` logic.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Core Utility Standardization' (Protocol in workflow.md)

## Phase 2: Refactor Identification Logic
- [ ] Task: Refactor `label_marks_complete.py` to remove local utility definitions and adopt `shared_utils`.
- [ ] Task: Implement the two-phase "Shazam-all-then-Local-all" strategy in `label_marks_complete.py`.
- [ ] Task: Write a regression test in `tests/test_identification_strategy.py` that mocks Shazam and Local DB to verify the attempt sequence.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Refactor Identification Logic' (Protocol in workflow.md)

## Phase 3: Synchronize Learning and Reinforcement
- [ ] Task: Update `learn_songs.py` to use `shared_utils` for window generation and duration.
- [ ] Task: Verify `learn_songs.py` correctly handles song name overlaps by adding new fingerprints to existing entries.
- [ ] Task: Create an integration test `tests/test_reinforcement_learning.py` that:
    1. Simulates an "Unidentified" marker.
    2. Runs `learn_songs.py` to "identify" it.
    3. Verifies `label_marks_complete.py` (via `dna_matcher`) now recognizes it locally.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Synchronize Learning and Reinforcement' (Protocol in workflow.md)
