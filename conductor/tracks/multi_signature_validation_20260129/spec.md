# Track Specification - Multi-Signature Validation

## Overview
Confirm and validate that the local "Audio DNA" system correctly handles multiple versions of the same song (covers/mixes) under a single name. Ensure the learning process is additive and the matching process is exhaustive.

## Functional Requirements
1.  **Reinforcement Verification:** Ensure `learn_songs.py` correctly appends new fingerprints to an existing song entry in `song_memory.db` without creating duplicates or errors.
2.  **Variant Recognition Test:** Create a regression test that:
    - Learns a "Base" signature for a song name.
    - Learns a "Variant" signature for the same song name.
    - Successfully identifies a clip of the "Variant" audio as the original song name.
3.  **Performance Check:** Verify that the "Exhaustive Match" logic in `dna_matcher.py` (which checks every signature) remains fast even with multiple signatures per song.

## Acceptance Criteria
1.  A dedicated test script (`tests/test_variant_recognition.py`) passes, proving that two different audio clips can map to the same name.
2.  The database `songs` table remains clean (no duplicate names).
3.  `product.md` is updated to explicitly mention "Multi-Signature Support" as a feature.

## Out of Scope
- Changing the fingerprinting algorithm.
- Modifying Shazam logic.
