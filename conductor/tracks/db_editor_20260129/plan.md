# Implementation Plan - Local Database Name Editor

## Phase 1: Core Logic and Utility
- [x] Task: Create `manage_database.py` with an `export_names()` function.
    - [x] Connect to `song_memory.db`.
    - [x] Fetch all names from the `songs` table.
    - [x] Write to `db_names.json` in the format `{"name": "name"}`.
- [x] Task: Implement `import_names()` function in `manage_database.py`.
    - [x] Read `db_names.json`.
    - [x] For each key-value pair where `key != value`:
        - [x] Execute `UPDATE songs SET name = ? WHERE name = ?`.
- [x] Task: Conductor - User Manual Verification 'Phase 1: Core Logic and Utility' (Protocol in workflow.md)

## Phase 2: Integration and Safety
- [x] Task: Add basic error handling (e.g., file not found, DB connection issues).
- [x] Task: Create a command-line interface for the script (e.g., `python manage_database.py --export` and `--import`).
- [x] Task: Write a unit test `tests/test_db_editor.py` that:
    - [x] Creates a temporary test DB.
    - [x] Exports names.
    - [x] Mocks an edit.
    - [x] Imports and verifies the DB update.
- [x] Task: Conductor - User Manual Verification 'Phase 2: Integration and Safety' (Protocol in workflow.md)

## Phase 3: Documentation and Cleanup
- [x] Task: Add help text to the script.
- [x] Task: Final end-to-end verification with the real `song_memory.db`.
- [x] Task: Conductor - User Manual Verification 'Phase 3: Documentation and Cleanup' (Protocol in workflow.md)
