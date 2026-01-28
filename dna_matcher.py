import numpy as np
from song_memory_manager import SongMemoryManager

class DNAMatcher:
    def __init__(self, db_path="song_memory.db"):
        self.manager = SongMemoryManager(db_path)
        self.signatures = self.manager.get_all_signatures()

    def find_match(self, target_fp, threshold=0.9):
        """
        Finds the best matching song name for a given target fingerprint.
        Returns (name, score) or (None, 0.0)
        """
        if not self.signatures:
            return None, 0.0
            
        target_fp = np.array(target_fp)
        target_norm = np.linalg.norm(target_fp)
        
        if target_norm == 0:
            return None, 0.0
            
        best_name = None
        best_score = 0.0
        
        for name, sig_fp in self.signatures:
            sig_fp = np.array(sig_fp)
            sig_norm = np.linalg.norm(sig_fp)
            
            if sig_norm == 0:
                continue
                
            # Cosine Similarity
            score = np.dot(target_fp, sig_fp) / (target_norm * sig_norm)
            
            if score > best_score:
                best_score = score
                best_name = name
                
        if best_score >= threshold:
            return best_name, best_score
            
        return None, best_score
