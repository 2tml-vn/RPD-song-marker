# Track Specification - Consistent Identification Pipeline

## Overview
Unify the "order of attempts" (sliding window logic) across the identification and learning modules to ensure deterministic behavior. This ensures that if a song is learned from a specific duration, it will be reliably recognized using the same windowing strategy in future sessions.

## Functional Requirements
1.  **Centralize Core Utilities:** Ensure `get_optimal_sliding_windows`, `parse_ts`, and `format_song_entry` are correctly implemented in `shared_utils.py` and used by all relevant scripts.
2.  **Standardize Window Duration:** Set `WINDOW_DURATION` to 10.0 seconds globally in `shared_utils.py`.
3.  **Deterministic Identification Strategy:**
    *   For a given gap, generate windows using the "Center-Out" strategy in `shared_utils.py`.
    *   **Phase 1 (Shazam):** Attempt identification using Shazam for ALL windows in the generated order. If a match is found, return immediately.
    *   **Phase 2 (Local Fallback):** If (and only if) all Shazam attempts fail, attempt matching against the local `song_memory.db` for ALL windows in the same generated order.
4.  **Module Synchronization:**
    *   Update `label_marks_complete.py` to use the shared utilities and the "Shazam-all-then-Local-all" strategy.
    *   Ensure `learn_songs.py` uses the exact same `shared_utils` logic to generate fingerprints for the local database.
5.  **Reinforcement Learning:** `learn_songs.py` must support adding new fingerprints to existing song entries in `song_memory.db` when a user provides a name for an "Unidentified" segment, even if that song name already exists in the database.

## Acceptance Criteria
1.  `label_marks_complete.py` correctly implements the "Shazam-all-then-Local-all" sequence for every marker.
2.  Local DB matching is only triggered after all Shazam attempts for a marker have failed.
3.  `learn_songs.py` uses the identical windowing offsets as `label_marks_complete.py` for the same gap size.
4.  Running `learn_songs.py` on a previously "Unidentified" segment allows the system to recognize that segment locally in subsequent runs.
