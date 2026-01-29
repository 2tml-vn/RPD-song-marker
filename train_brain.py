import sqlite3
import json
import numpy as np
import joblib
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import LabelEncoder
import os

DB_PATH = 'song_memory.db'
MODEL_PATH = 'local_brain.joblib'
LABEL_PATH = 'label_encoder.joblib'

def train_brain():
    if not os.path.exists(DB_PATH):
        print("Error: Database not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.name, sig.fingerprint 
        FROM signatures sig
        JOIN songs s ON sig.song_id = s.id
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("No signatures found in database.")
        return

    X = []
    y = []
    
    for name, fp_json in rows:
        X.append(json.loads(fp_json))
        y.append(name)
        
    X = np.array(X)
    le = LabelEncoder()
    y_encoded = le.fit_transform(y)
    
    print(f"Training KNN Brain on {len(X)} samples across {len(le.classes_)} songs...")

    # Use 1-Nearest Neighbor for maximum surgical precision
    # Since we want to match EXACT spectral fingerprints
    clf = KNeighborsClassifier(n_neighbors=1, metric='euclidean')
    clf.fit(X, y_encoded)

    joblib.dump(clf, MODEL_PATH)
    joblib.dump(le, LABEL_PATH)
    print(f"SUCCESS: KNN Brain saved to {MODEL_PATH}")

if __name__ == "__main__":
    train_brain()