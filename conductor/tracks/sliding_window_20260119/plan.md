# Implementation Plan - Optimal Dynamic Sliding Window

## Phase 1: Logic Engine Implementation
- [x] Task: Create unit tests for the sliding window calculation (calculating N and Step). f74261f
- [x] Task: Implement `get_optimal_sliding_windows(gap_size)` helper function in `label_marks_complete.py`. f74261f
- [x] Task: Refactor the core processing loop to iterate through the dynamically generated windows. 144e2c2
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Logic Engine Implementation' (Protocol in workflow.md)

## Phase 2: Integration & Robustness
- [ ] Task: Update the `ffmpeg` cutting logic to use the dynamic `start_offset` and `duration` for each try.
- [ ] Task: Ensure the "Immediate Exit" logic works (stopping retries the moment Shazam returns a match).
- [ ] Task: Verify that short gaps (<12s) are handled correctly without exceeding boundaries.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Integration & Robustness' (Protocol in workflow.md)
