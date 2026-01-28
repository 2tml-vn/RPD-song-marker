# Implementation Plan - Global Database Deduplication

## Phase 1: Database Cleanup & Schema Update
- [x] Task: Execute a SQL script to deduplicate current data and add the `UNIQUE` index.
    - [x] Create a backup of `song_memory.db`.
    - [x] Run SQL to delete duplicates based on the `fingerprint` column.
    - [x] Alter the table to add a UNIQUE constraint/index on `fingerprint`.
- [~] Task: Conductor - User Manual Verification 'Phase 1: Database Cleanup & Schema Update' (Protocol in workflow.md)

## Phase 2: Logic and Reporting Update
- [ ] Task: Update `SongMemoryManager.add_song` in `song_memory_manager.py`.
    - [ ] Change `INSERT` to `INSERT OR IGNORE`.
    - [ ] Update the return value or track the count of successful vs ignored inserts.
- [ ] Task: Update `learn_songs.py` to report new vs skipped signatures.
    - [ ] Log "Added X new signatures, Skipped Y existing" for each song.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Logic and Reporting Update' (Protocol in workflow.md)

## Phase 3: Verification & Integration Test
- [ ] Task: Create `tests/test_global_deduplication.py` to:
    - [ ] Mock a learning session.
    - [ ] Run it twice.
    - [ ] Assert the DB only contains one set of entries.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Verification & Integration Test' (Protocol in workflow.md)
