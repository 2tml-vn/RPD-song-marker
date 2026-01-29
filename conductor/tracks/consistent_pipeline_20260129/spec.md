# Track Specification - Robust Best-Match Pipeline

## Overview
Implement a "Consensus Matching" strategy and frame-level normalization to eliminate false positives in local identification. By analyzing the entire gap before deciding on a match, we prevent "lucky" single-window hits from triggering incorrect identifications.

## Functional Requirements
1.  **Frame-Level Normalization (audio_fingerprinter.py):**
    - Update the MFCC extraction loop to normalize each 25ms frame to unit energy. 
    - This ensures the math is 100% volume-independent.
2.  **Consensus Best-Match Strategy (label_marks_complete.py):**
    - Refactor the local matching loop to perform a **complete scan** of all high-density windows in the gap.
    - Instead of returning on the first 0.9 match, the system must collect all matches and pick the absolute **highest overall similarity score** found in the entire sequence.
3.  **Threshold Guard:**
    - Only accept the "Best Match" if its score exceeds the 0.9 threshold.
4.  **Enhanced Transparency:**
    - Maintain and improve the "Top 3 Candidates" logging to show the system's reasoning for the final winner.

## Acceptance Criteria
1.  False positives for unknown songs are eliminated (verified by checking previously problematic segments).
2.  Identification remains robust for learned songs (high similarity for true matches).
3.  Debug logs clearly show the winner vs. runners-up for every identification attempt.
