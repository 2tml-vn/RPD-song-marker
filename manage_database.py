import sqlite3
import json
import os
import argparse

def export_names(db_path="song_memory.db", json_path="db_names.json"):
    """Fetches all names from the songs table and writes to JSON."""
    if not os.path.exists(db_path):
        print(f"Error: Database {db_path} not found.")
        return

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM songs")
            rows = cursor.fetchall()
            
        names = {row[0]: row[0] for row in rows}
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(names, f, indent=4, ensure_ascii=False)
        
        print(f"Exported {len(names)} names to {json_path}")
    except sqlite3.Error as e:
        print(f"Database error during export: {e}")
    except Exception as e:
        print(f"Unexpected error during export: {e}")

def import_names(db_path="song_memory.db", json_path="db_names.json"):
    """Reads JSON and updates the songs table where names have changed."""
    if not os.path.exists(json_path):
        print(f"Error: JSON file {json_path} not found.")
        return
    
    if not os.path.exists(db_path):
        print(f"Error: Database {db_path} not found.")
        return

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            new_names = json.load(f)
            
        update_count = 0
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            for old_name, new_name in new_names.items():
                if old_name != new_name:
                    cursor.execute("UPDATE songs SET name = ? WHERE name = ?", (new_name, old_name))
                    if cursor.rowcount > 0:
                        update_count += 1
            conn.commit()
            
        print(f"Successfully updated {update_count} song names in {db_path}")
    except json.JSONDecodeError:
        print(f"Error: Failed to decode JSON from {json_path}. Ensure it is valid.")
    except sqlite3.Error as e:
        print(f"Database error during import: {e}")
    except Exception as e:
        print(f"Unexpected error during import: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage Local Database Names")
    parser.add_argument("--export", action="store_true", help="Export names to JSON")
    parser.add_argument("--import-names", action="store_true", help="Import names from JSON")
    parser.add_argument("--db", default="song_memory.db", help="Path to database")
    parser.add_argument("--json", default="db_names.json", help="Path to JSON file")
    
    args = parser.parse_args()
    
    if args.export:
        export_names(args.db, args.json)
    elif args.import_names:
        import_names(args.db, args.json)
    else:
        parser.print_help()
