import numpy as np
import joblib
import os
from song_memory_manager import SongMemoryManager

MODEL_PATH = 'local_brain.joblib'
LABEL_PATH = 'label_encoder.joblib'

class DNAMatcher:
    def __init__(self, db_path="song_memory.db"):
        self.manager = SongMemoryManager(db_path)
        self.model = None
        self.le = None
        self.signatures = None
        self.load_brain()

    def load_brain(self):
        if os.path.exists(MODEL_PATH) and os.path.exists(LABEL_PATH):
            try:
                self.model = joblib.load(MODEL_PATH)
                self.le = joblib.load(LABEL_PATH)
                print("KNN Brain loaded successfully.")
            except Exception as e:
                print(f"Warning: Failed to load brain: {e}")
        else:
            print("Warning: local_brain.joblib not found. Using fallback math.")
            self.signatures = self.manager.get_all_signatures()

    def find_match(self, target_fp, threshold=0.95):
        """
        Finds match using KNN Distance.
        Threshold 0.95 = Max Distance 0.05.
        """
        target_fp = np.array(target_fp).reshape(1, -1)
        
        if self.model and self.le:
            try:
                # 1. Get neighbors
                distances, indices = self.model.kneighbors(target_fp, n_neighbors=3)
                
                # 2. Map indices to actual labels
                # model.predict returns the labels directly but doesn't give us the distance
                best_label_encoded = self.model.predict(target_fp)[0]
                name = self.le.inverse_transform([best_label_encoded])[0]
                
                # Distance to the ABSOLUTE nearest sample
                dist = float(distances[0][0])
                score = 1.0 - dist
                
                # 3. Get top candidates for logs
                top_candidates = []
                for d, idx in zip(distances[0], indices[0]):
                    # Map training sample index to its class label
                    label_idx = self.model._y[idx]
                    cand_name = self.le.inverse_transform([label_idx])[0]
                    top_candidates.append((cand_name, float(1.0 - d)))

                if score >= threshold:
                    return name, score, top_candidates
                else:
                    return None, score, top_candidates
            except Exception as e:
                print(f"ML Match Error: {e}")
        
        # Fallback to pure Cosine Similarity
        if not self.signatures:
            self.signatures = self.manager.get_all_signatures()
        if not self.signatures:
            return None, 0.0, []
            
        target_norm = np.linalg.norm(target_fp)
        if target_norm == 0: return None, 0.0, []
        
        scores = []
        for name, sig_fp in self.signatures:
            sig_fp = np.array(sig_fp)
            sig_norm = np.linalg.norm(sig_fp)
            if sig_norm == 0: continue
            sim = np.dot(target_fp.flatten(), sig_fp) / (target_norm * sig_norm)
            scores.append((name, float(sim)))
            
        scores.sort(key=lambda x: x[1], reverse=True)
        top_candidates = scores[:3]
        
        if top_candidates and top_candidates[0][1] >= threshold:
            return top_candidates[0][0], top_candidates[0][1], top_candidates
            
        return None, (top_candidates[0][1] if top_candidates else 0.0), top_candidates
