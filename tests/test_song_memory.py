import os
import sqlite3
import numpy as np
import pytest
from song_memory_manager import SongMemoryManager

@pytest.fixture
def db_path(tmp_path):
    d = tmp_path / "song_memory.db"
    return str(d)

def test_add_and_get_song(db_path):
    manager = SongMemoryManager(db_path)
    
    # Mock fingerprint
    fp = np.random.rand(128).tolist()
    
    manager.add_song("Test Song", [fp])
    
    songs = manager.get_all_songs()
    assert len(songs) == 1
    assert songs[0]['name'] == "Test Song"
    
    sigs = manager.get_signatures_for_song(songs[0]['id'])
    assert len(sigs) == 1
    assert np.allclose(sigs[0], fp)

def test_multiple_signatures(db_path):
    manager = SongMemoryManager(db_path)
    fp1 = [1.0, 2.0, 3.0]
    fp2 = [4.0, 5.0, 6.0]
    
    manager.add_song("Multi Sig Song", [fp1, fp2])
    
    song = manager.get_all_songs()[0]
    sigs = manager.get_signatures_for_song(song['id'])
    assert len(sigs) == 2
    assert fp1 in sigs
    assert fp2 in sigs
