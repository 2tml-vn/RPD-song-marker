import acoustid
import os

API_KEY = 'c9398019-f0a5-4841-a83d-0d6f6e52c803' 
FPCALC_PATH = os.path.abspath('./fpcalc.exe')
acoustid.FPCALC = FPCALC_PATH

def test_identify(path):
    print(f"Testing AcoustID for: {path}")
    try:
        duration, fingerprint = acoustid.fingerprint_file(path)
        print(f"Fingerprint generated. Duration: {duration}s")
        
        response = acoustid.lookup(API_KEY, fingerprint, duration)
        print("Response received from AcoustID.")
        
        if response['status'] == 'ok':
            results = response.get('results', [])
            if not results:
                print("No matches found.")
                return
            
            for result in results:
                score = result.get('score')
                recordings = result.get('recordings', [])
                for rec in recordings:
                    title = rec.get('title')
                    artists = rec.get('artists', [{}])
                    artist_name = artists[0].get('name') if artists else "Unknown"
                    print(f"Match: {title} - {artist_name} (Score: {score:.2f})")
        else:
            print(f"Error status: {response.get('status')}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_file = "runs/C_omZX8X_-A/test_snippet_1_33.m4a"
    test_identify(test_file)