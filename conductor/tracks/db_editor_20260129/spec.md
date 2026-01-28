# Track Specification - Local Database Name Editor (JSON Import/Export)

## Overview
Provide a reliable way to manage and correct song names stored in the local `song_memory.db`. Instead of manual SQL editing, this track implements a safe JSON-based workflow for batch renaming songs.

## Functional Requirements
1.  **Export Tool:** Create a utility to export all unique song names from the `songs` table into a structured JSON file (e.g., `db_names.json`).
    - Format: `{"Original Name": "New Name"}` (Initially both values will be the same).
2.  **Import Tool:** Create a utility to read the edited JSON and update the `songs` table.
    - It should perform an `UPDATE` SQL command for every entry where the value differs from the key.
    - If an entry from the database is missing in the JSON, it remains untouched (no deletions).
3.  **Conflict Handling:** The tool assumes no name conflicts will occur (one-to-one mapping).
4.  **Verification:** Print a summary of changes (e.g., "Updated 5 song names") after the import process.

## Acceptance Criteria
1.  Running the export command generates a valid `db_names.json` containing all songs from the local database.
2.  Editing a value in the JSON and running the import command successfully updates the name in `song_memory.db`.
3.  Subsequent runs of `label_marks_complete.py` correctly identify songs using the updated names.
4.  Deleting an entry from the JSON and re-importing does NOT delete the song from the database.

## Out of Scope
- Merging songs with identical names.
- Deleting songs or fingerprints via this tool.
- Editing fingerprints/DNA data.
