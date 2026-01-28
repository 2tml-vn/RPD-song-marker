import sqlite3
import json
import os

class SongMemoryManager:
    def __init__(self, db_path="song_memory.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS songs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS signatures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    song_id INTEGER,
                    fingerprint TEXT UNIQUE,
                    FOREIGN KEY (song_id) REFERENCES songs (id)
                )
            """)
            conn.commit()

    def add_song(self, name, fingerprints):
        """
        Adds a song and its associated fingerprints.
        Returns a tuple of (added_count, skipped_count).
        """
        added_count = 0
        skipped_count = 0
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO songs (name) VALUES (?)", (name,))
                song_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                cursor.execute("SELECT id FROM songs WHERE name = ?", (name,))
                song_id = cursor.fetchone()[0]

            for fp in fingerprints:
                cursor.execute("INSERT OR IGNORE INTO signatures (song_id, fingerprint) VALUES (?, ?)", 
                             (song_id, json.dumps(fp)))
                if cursor.rowcount > 0:
                    added_count += 1
                else:
                    skipped_count += 1
            conn.commit()
        return added_count, skipped_count

    def get_all_songs(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM songs")
            return [dict(row) for row in cursor.fetchall()]

    def get_signatures_for_song(self, song_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT fingerprint FROM signatures WHERE song_id = ?", (song_id,))
            return [json.loads(row[0]) for row in cursor.fetchall()]

    def get_all_signatures(self):
        """Returns a list of (song_name, fingerprint) tuples."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.name, sig.fingerprint 
                FROM signatures sig
                JOIN songs s ON sig.song_id = s.id
            """)
            return [(row[0], json.loads(row[1])) for row in cursor.fetchall()]
