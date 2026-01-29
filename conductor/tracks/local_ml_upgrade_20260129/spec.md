# Track Specification - Self-Trained Local ML Upgrade

## Overview
Replace the current "Averaging" math with a self-trained local Neural Machine Learning engine. By utilizing high-dimensional spectral features and a custom-trained Neural Network (MLP), the system will achieve high-precision identification that is immune to "genre noise" and volume fluctuations.

## Functional Requirements
1.  **High-Dimensional Feature Extraction (audio_features.py):**
    - Utilize `librosa` to extract 150+ dimensions of audio DNA.
    - Features include: MFCC (20), Chroma (12), Tonnetz (6), Spectral Contrast (7), and their statistical variations (Mean, StdDev, Delta).
2.  **Local Training Loop (train_brain.py):**
    - Implement a script to train a **Multi-Layer Perceptron (MLP)** Neural Network from scratch using signatures stored in the local database.
    - Save the trained model locally as `local_brain.joblib`.
3.  **Neural Identity Database (song_memory_manager.py):**
    - Update the `signatures` table to store high-dimensional feature vectors.
4.  **Local Inference Engine (dna_matcher.py):**
    - Refactor to use the locally trained `local_brain.joblib`.
    - Implement a **Probability-Based Guard**: Matches are rejected if the AI's confidence is below a defined threshold (e.g., 80%).

## Technical Constraints
- **100% Local:** All training and inference must happen on the local CPU. No external APIs or cloud services.
- **Dependency:** Add `librosa` and `scikit-learn` to `requirements.txt`.

## Acceptance Criteria
1.  False positives for unknown segments drop to near zero.
2.  True matches for learned songs remain > 90% accurate.
3.  The model can be retrained in seconds as new songs are added to the library.
