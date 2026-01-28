# Implementation Plan - High-Fidelity Audio DNA

## Phase 1: Mathematical Engine Upgrade [checkpoint: high_precision_math_verified]
- [x] Task: Update `audio_fingerprinter.py` to use Mel-Frequency Cepstral Coefficients (MFCCs).
    - [x] Implement MFCC calculation (13 coefficients).
    - [x] Calculate both Mean and Standard Deviation for the vector.
    - [x] Ensure 100% volume-independence via normalization.
- [x] Task: Create `tests/test_precision_math.py` to verify that "Song A" and "Song B" produce distinct fingerprints.
- [x] Task: Conductor - User Manual Verification 'Phase 1: Mathematical Engine Upgrade' (Protocol in workflow.md)

## Phase 2: High-Density Matching Strategy [checkpoint: high_density_matching_ready]
- [x] Task: Create a new utility function in `shared_utils.py` for local window generation.
    - [x] `get_local_matching_windows(gap_size)`: Returns 5s windows with 50% overlap (2.5s step).
- [x] Task: Refactor Phase 2 of `identify_song` in `label_marks_complete.py`.
    - [x] Use the new high-density local windows.
    - [x] Update debug logs to show the top similarity scores for transparency.
- [x] Task: Conductor - User Manual Verification 'Phase 2: High-Density Matching Strategy' (Protocol in workflow.md)

## Phase 3: Migration & Learning Sync [checkpoint: hifi_dna_fully_synced]
- [x] Task: Create `migrate_database.py` to backup and clear the `signatures` table.
- [x] Task: Update `learn_songs.py` to use the new 5s high-density strategy for reinforcing the database.
- [x] Task: Final end-to-end verification:
    - [x] Learn a song.
    - [x] Verify 100% accurate local identification on a different clip of the same song.
- [x] Task: Conductor - User Manual Verification 'Phase 3: Migration & Learning Sync' (Protocol in workflow.md)
