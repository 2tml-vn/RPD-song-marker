import unittest
import sqlite3
import json
import os
from pathlib import Path
import sys

# Add parent directory to path to import manage_database
sys.path.append(str(Path(__file__).resolve().parent.parent))

class TestManageDatabase(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_song_memory.db"
        self.json_path = "test_db_names.json"
        
        # Cleanup before start
        for p in [self.db_path, self.json_path]:
            if os.path.exists(p):
                try: os.remove(p)
                except: pass
        
        # Init test DB
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS songs")
            cursor.execute("CREATE TABLE songs (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE)")
            cursor.execute("INSERT INTO songs (name) VALUES (?)", ("Song A",))
            cursor.execute("INSERT INTO songs (name) VALUES (?)", ("Song B",))
            conn.commit()

    def tearDown(self):
        # Add a small delay to allow sqlite to release locks if any
        import time
        time.sleep(0.1)
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                # If still locked, we'll try again once or ignore
                time.sleep(0.5)
                try:
                    os.remove(self.db_path)
                except:
                    pass
        if os.path.exists(self.json_path):
            try:
                os.remove(self.json_path)
            except:
                pass

    def test_export_names(self):
        from manage_database import export_names
        export_names(self.db_path, self.json_path)
        
        self.assertTrue(os.path.exists(self.json_path))
        with open(self.json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        self.assertEqual(data, {"Song A": "Song A", "Song B": "Song B"})

    def test_import_names(self):
        from manage_database import export_names, import_names
        export_names(self.db_path, self.json_path)
        
        # Edit JSON
        with open(self.json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["Song A"] = "Song A (Renamed)"
        with open(self.json_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
            
        import_names(self.db_path, self.json_path)
        
        # Verify DB
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM songs ORDER BY name")
            names = [row[0] for row in cursor.fetchall()]
        
        self.assertIn("Song A (Renamed)", names)
        self.assertIn("Song B", names)
        self.assertNotIn("Song A", names)

if __name__ == "__main__":
    unittest.main()
