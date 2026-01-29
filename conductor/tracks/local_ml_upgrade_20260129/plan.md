# Implementation Plan - Self-Trained Local ML Upgrade

## Phase 1: Feature Engine (The "Eyes and Ears")
- [x] Task: Update `requirements.txt` with `librosa`.
- [x] Task: Create `audio_features.py` to extract 150+ dimensions of raw audio DNA (MFCC, Chroma, Spectral Contrast, Tonnetz).
- [x] Task: Verify that different songs produce significantly different "feature maps."
- [x] Task: Conductor - User Manual Verification 'Phase 1: Feature Engine' (Protocol in workflow.md)

## Phase 2: The Training Loop (The "Teacher")
- [x] Task: Create `train_brain.py`.
    - [x] Script reads all learned signatures from `song_memory.db`.
    - [x] Trains a **Neural Network (MLP)** using Scikit-Learn.
    - [x] Evaluates accuracy and saves the result to `local_brain.joblib`.
- [x] Task: Update `learn_songs.py` to prompt the user to "Re-train Brain" after adding new songs.
- [x] Task: Conductor - User Manual Verification 'Phase 2: The Training Loop' (Protocol in workflow.md)

## Phase 3: Neural Matching (The "Brain")
- [x] Task: Refactor `dna_matcher.py` to use the `local_brain.joblib`.
- [x] Task: Implement **Probability Guard**: If the AI is less than 80% sure, it returns "Unidentified" to prevent false positives.
- [x] Task: Conductor - User Manual Verification 'Phase 3: Neural Matching' (Protocol in workflow.md)

## Phase 4: Final Verification
- [x] Task: Wipe old database signatures.
- [x] Task: Re-learn your core songs using the new 150-dim feature engine.
- [x] Task: Run the "Battle Test" against the 10:27 segment to confirm it finally stays Unidentified.
- [x] Task: Conductor - User Manual Verification 'Phase 4: Final Verification' (Protocol in workflow.md)
