# Track Specification - High-Fidelity Audio DNA

## Overview
Rebuild the local "Audio DNA" system for maximum precision and zero false positives. This involves upgrading the mathematical feature set to include Mel-Frequency Cepstral Coefficients (MFCCs) and Rhythmic Texture (StdDev), and transitioning to a high-density 5-second local matching strategy.

## Functional Requirements
1.  **Upgraded Math (audio_fingerprinter.py):**
    - Transition to **MFCC-based features** (13 coefficients).
    - Calculate **Mean and Standard Deviation** for each coefficient across the window.
    - Ensure features are volume-independent via strict normalization.
2.  **Local Matching Strategy (label_marks_complete.py):**
    - Transition to a **fixed 5-second local window**.
    - Implement a **High-Density Scan**: generate windows with 50% overlap (2.5s step) across the entire gap for local database fallback.
    - Maintain the 0.9 similarity threshold.
3.  **Database Migration:**
    - Provide a script to backup and wipe the `signatures` table in `song_memory.db` to ensure all active data uses the new math.
4.  **Reporting:**
    - Update debug logs to show the top 3 similarity scores for transparency during matching.

## Acceptance Criteria
1.  False positives are eliminated for songs not in the database.
2.  `learn_songs.py` generates high-fidelity 5-second signatures.
3.  `dna_matcher.py` correctly identifies variant versions using the new 26-dimensional statistical fingerprints.

## Out of Scope
- Implementing Deep Learning/Neural Network models.
- Changing the primary Shazam API integration.
