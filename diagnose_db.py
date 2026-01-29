import sqlite3
import json
import numpy as np

def analyze_db():
    conn = sqlite3.connect('song_memory.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, name FROM songs")
    songs = cursor.fetchall()
    print(f"--- Database Songs ({len(songs)}) ---")
    for sid, name in songs:
        cursor.execute("SELECT count(*) FROM signatures WHERE song_id = ?", (sid,))
        count = cursor.fetchone()[0]
        print(f"ID {sid}: {name} ({count} signatures)")

    cursor.execute("SELECT s.name, sig.fingerprint FROM signatures sig JOIN songs s ON sig.song_id = s.id LIMIT 1")
    row = cursor.fetchone()
    if row:
        fp = np.array(json.loads(row[1]))
        print(f"\nExample Fingerprint Dimension: {len(fp)}")
    
    conn.close()

if __name__ == "__main__":
    analyze_db()
