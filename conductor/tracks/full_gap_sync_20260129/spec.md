# Track Specification - Comprehensive Full-Gap Identification & Learning

## Overview
Ensure that every identification and learning task concludes with a "Full Duration" attempt covering the entire audio segment defined by the marker gap. This ensures 100% data coverage and improves the chances of matching against longer or unique song segments.

## Functional Requirements
1.  **Guaranteed Final Attempt:**
    - Update `shared_utils.get_optimal_sliding_windows` to ensure the final window in the list is always `(0.0, gap_size)`.
    - **Exception:** If `gap_size <= WINDOW_DURATION`, do not add a second window (since the first one already covers the full gap).
2.  **Full-Gap Learning:**
    - Ensure `learn_songs.py` correctly processes this final full-gap window.
    - The resulting fingerprint should be stored as a standard signature in the `signatures` table.
3.  **Pipeline Synchronization:**
    - Verify that `label_marks_complete.py` (both Phase 1 and Phase 2) naturally inherits this updated window list from `shared_utils`.

## Acceptance Criteria
1.  For a 15-second gap, `get_optimal_sliding_windows` returns its standard windows plus a final `(0.0, 15.0)` window.
2.  For an 8-second gap, `get_optimal_sliding_windows` returns only the single `(0.0, 8.0)` window (no duplicates).
3.  `learn_songs.py` logs show the processing of the final full-gap window for every unidentified song.
4.  Identification runs (Shazam and Local) explicitly attempt the full gap as their final fallback.

## Out of Scope
- Changing the "Center-Out" sorting logic for the intermediate windows.
- Modifying the 10-second `WINDOW_DURATION` constant.
