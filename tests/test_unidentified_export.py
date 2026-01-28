import json
import os
from pathlib import Path
import pytest

def test_unidentified_json_structure(tmp_path):
    # Setup mock data
    results = {
        "0:00": "Song A - Artist A",
        "1:00": "Unidentified",
        "2:30": "Song B - Artist B",
        "3:45": "Unidentified"
    }
    video_id = "test_vid"
    video_dir = tmp_path / "runs" / video_id
    video_dir.mkdir(parents=True)
    
    unidentified_file = video_dir / "unidentified.json"
    
    # Logic to be implemented in the script
    sorted_keys = sorted(results.keys())
    unidentified_data = {}
    
    for i, m in enumerate(sorted_keys):
        if results[m] == "Unidentified":
            next_m = sorted_keys[i+1] if i+1 < len(sorted_keys) else "END"
            unidentified_data[m] = {
                "end": next_m,
                "name": ""
            }
            
    with open(unidentified_file, "w", encoding="utf-8") as f:
        json.dump(unidentified_data, f, indent=2)
        
    # Verify
    assert unidentified_file.exists()
    with open(unidentified_file, "r") as f:
        data = json.load(f)
        
    assert "1:00" in data
    assert data["1:00"]["end"] == "2:30"
    assert data["1:00"]["name"] == ""
    
    assert "3:45" in data
    assert data["3:45"]["end"] == "END"
