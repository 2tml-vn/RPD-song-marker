import numpy as np
from song_memory_manager import SongMemoryManager

class DNAMatcher:
    def __init__(self, db_path="song_memory.db"):
        self.manager = SongMemoryManager(db_path)
        self.signatures = self.manager.get_all_signatures()

    def find_match(self, target_fp, threshold=0.9):
        """
        Finds the best matching song name for a given target fingerprint.
        Returns (name, score, top_candidates)
        """
        if not self.signatures:
            return None, 0.0, []
            
        target_fp = np.array(target_fp)
        target_norm = np.linalg.norm(target_fp)
        
        if target_norm == 0:
            return None, 0.0, []
            
        scores = []
        for name, sig_fp in self.signatures:
            sig_fp = np.array(sig_fp)
            sig_norm = np.linalg.norm(sig_fp)
            
            if sig_norm == 0:
                continue
                
            # Cosine Similarity
            score = np.dot(target_fp, sig_fp) / (target_norm * sig_norm)
            scores.append((name, float(score)))
            
        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        top_candidates = scores[:3]
        
        if top_candidates and top_candidates[0][1] >= threshold:
            return top_candidates[0][0], top_candidates[0][1], top_candidates
            
        return None, (top_candidates[0][1] if top_candidates else 0.0), top_candidates