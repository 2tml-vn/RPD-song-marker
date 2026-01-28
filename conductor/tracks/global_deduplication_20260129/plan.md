# Implementation Plan - Global Database Deduplication

## Phase 1: Database Cleanup & Schema Update [checkpoint: 42fed70]
- [x] Task: Execute a SQL script to deduplicate current data and add the `UNIQUE` index.
    - [x] Create a backup of `song_memory.db`.
    - [x] Run SQL to delete duplicates based on the `fingerprint` column.
    - [x] Alter the table to add a UNIQUE constraint/index on `fingerprint`.
- [x] Task: Conductor - User Manual Verification 'Phase 1: Database Cleanup & Schema Update' (Protocol in workflow.md)

## Phase 2: Logic and Reporting Update [checkpoint: 25c9c4b]
- [x] Task: Update `SongMemoryManager.add_song` in `song_memory_manager.py`.
    - [x] Change `INSERT` to `INSERT OR IGNORE`.
    - [x] Update the return value or track the count of successful vs ignored inserts.
- [x] Task: Update `learn_songs.py` to report new vs skipped signatures.
    - [x] Log "Added X new signatures, Skipped Y existing" for each song.
- [x] Task: Conductor - User Manual Verification 'Phase 2: Logic and Reporting Update' (Protocol in workflow.md)

## Phase 3: Verification & Integration Test
- [ ] Task: Create `tests/test_global_deduplication.py` to:
    - [ ] Mock a learning session.
    - [ ] Run it twice.
    - [ ] Assert the DB only contains one set of entries.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Verification & Integration Test' (Protocol in workflow.md)
