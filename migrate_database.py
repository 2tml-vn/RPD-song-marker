import sqlite3
import shutil
import os

db_path = 'song_memory.db'
backup_path = 'song_memory.db.backup_old_math'

def migrate():
    if not os.path.exists(db_path):
        print("Database not found. Nothing to migrate.")
        return

    print(f"Creating backup at {backup_path}...")
    shutil.copy2(db_path, backup_path)

    print("Wiping signatures table to prepare for high-fidelity math...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM signatures")
    conn.commit()
    conn.close()
    print("Migration complete. You must now 're-learn' your songs using the updated learn_songs.py.")

if __name__ == "__main__":
    migrate()
