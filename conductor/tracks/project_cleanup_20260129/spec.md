# Track Specification - Project Directory Audit and Cleanup

## Overview
Perform a comprehensive audit of all files and folders in the project to identify and remove unused items. The goal is to minimize the codebase to only what is necessary for the `label_marks_complete.py` workflow and its direct dependencies.

## Functional Requirements
1.  **Comprehensive Iteration:** Audit every file and folder in the project root and all subdirectories.
2.  **Relevance Criteria:** An item is "Relevant" if it is:
    - Part of the `label_marks_complete.py` execution path (imports, config).
    - A direct dependency (e.g., `shared_utils.py`, `dna_matcher.py`).
    - Essential data or state (e.g., `song_memory.db`, `runs/` folder).
    - A core project document (e.g., `conductor/` files, `requirements.txt`).
3.  **Interactive Audit Stream:**
    - Read files one by one.
    - Explain the purpose of each file/folder.
    - Determine and announce if it is "Relevant" or "Unused" based on the criteria.
    - Ask for user confirmation before deleting or moving any "Unused" item.
4.  **Selective Cleanup:** Only delete items after explicit user approval.

## Acceptance Criteria
1.  The project directory is streamlined, containing only files and folders essential for the core music identification workflow.
2.  `label_marks_complete.py` remains fully functional after the cleanup.
3.  The user has confirmed the fate of every flagged "Unused" item.

## Out of Scope
- Modifying the logic of `label_marks_complete.py`.
- Consolidating files (this is strictly a cleanup of existing items).
