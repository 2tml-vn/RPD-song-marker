import numpy as np
import os
import pytest
from song_memory_manager import SongMemoryManager
from dna_matcher import DNAMatcher

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_matcher.db")

def test_dna_match_success(db_path):
    manager = SongMemoryManager(db_path)
    # Create a unique fingerprint
    base_fp = (np.arange(64) / 64.0).tolist()
    manager.add_song("Match Song", [base_fp])
    
    matcher = DNAMatcher(db_path)
    
    # Test with identical fingerprint
    name, score = matcher.find_match(base_fp)
    assert name == "Match Song"
    assert score > 0.99
    
    # Test with slight variation
    noise = np.random.normal(0, 0.01, 64)
    noisy_fp = (np.array(base_fp) + noise).tolist()
    name, score = matcher.find_match(noisy_fp)
    assert name == "Match Song"
    assert score > 0.9

def test_dna_match_fail(db_path):
    manager = SongMemoryManager(db_path)
    base_fp = (np.arange(64) / 64.0).tolist()
    manager.add_song("Song A", [base_fp])
    
    matcher = DNAMatcher(db_path)
    
    # Very different fingerprint
    fail_fp = (np.ones(64) - (np.arange(64) / 64.0)).tolist()
    name, score = matcher.find_match(fail_fp)
    assert name is None
    assert score < 0.9

if __name__ == "__main__":
    # If running with python
    import sys
    tmp = os.environ.get("TEMP", "/tmp")
    p = os.path.join(tmp, "manual_test.db")
    if os.path.exists(p): os.remove(p)
    test_dna_match_success(p)
    test_dna_match_fail(p)
    print("DNA Matcher tests passed!")
