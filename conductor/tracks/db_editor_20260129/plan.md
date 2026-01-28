# Implementation Plan - Local Database Name Editor

## Phase 1: Core Logic and Utility
- [ ] Task: Create `manage_database.py` with an `export_names()` function.
    - [ ] Connect to `song_memory.db`.
    - [ ] Fetch all names from the `songs` table.
    - [ ] Write to `db_names.json` in the format `{"name": "name"}`.
- [ ] Task: Implement `import_names()` function in `manage_database.py`.
    - [ ] Read `db_names.json`.
    - [ ] For each key-value pair where `key != value`:
        - [ ] Execute `UPDATE songs SET name = ? WHERE name = ?`.
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Core Logic and Utility' (Protocol in workflow.md)

## Phase 2: Integration and Safety
- [ ] Task: Add basic error handling (e.g., file not found, DB connection issues).
- [ ] Task: Create a command-line interface for the script (e.g., `python manage_database.py --export` and `--import`).
- [ ] Task: Write a unit test `tests/test_db_editor.py` that:
    - [ ] Creates a temporary test DB.
    - [ ] Exports names.
    - [ ] Mocks an edit.
    - [ ] Imports and verifies the DB update.
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Integration and Safety' (Protocol in workflow.md)

## Phase 3: Documentation and Cleanup
- [ ] Task: Add help text to the script.
- [ ] Task: Final end-to-end verification with the real `song_memory.db`.
- [ ] Task: Conductor - User Manual Verification 'Phase 3: Documentation and Cleanup' (Protocol in workflow.md)
