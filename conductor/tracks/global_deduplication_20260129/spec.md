# Track Specification - Global Database Deduplication

## Overview
Implement a global uniqueness constraint for the "Audio DNA" signatures in `song_memory.db`. This ensures that every unique fingerprint (list of 64 identical values) maps to exactly one song entry, preventing database bloat and ambiguous identification results.

## Functional Requirements
1.  **Global Deduplication (SQL):** 
    - Identify and remove all existing duplicate rows in the `signatures` table where the `fingerprint` JSON string is exactly identical.
    - If identical fingerprints point to different song names, keep only the first one encountered.
2.  **Schema Reinforcement:** 
    - Add a `UNIQUE` index to the `fingerprint` column in the `signatures` table to enforce global uniqueness at the database level.
3.  **Graceful Code Handling:** 
    - Update `SongMemoryManager.add_song` to use `INSERT OR IGNORE` or similar logic.
    - The learning script should continue processing without error if it attempts to add a fingerprint that already exists.
4.  **Reporting:** 
    - During the learning process, report the number of *new* signatures added versus the number of signatures *skipped* (duplicates).

## Acceptance Criteria
1.  A SQL check confirms that no two rows in the `signatures` table have the same `fingerprint` string.
2.  Running `learn_songs.py` twice on the same video results in "Added 0 new signatures, Skipped X duplicates" on the second run.
3.  Memory and identification performance are optimized by the smaller, cleaner database.

## Out of Scope
- Fuzzy deduplication (merging similar but non-identical fingerprints).
