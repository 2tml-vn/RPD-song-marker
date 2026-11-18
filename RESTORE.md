# Restoring this project on a new machine

STEP 0 — exists only outside the repo (your head/notes):
- GitHub login with access to the private repo
- Repo URL: https://github.com/2tml-vn/RPD-song-marker.git
- The key.age passphrase (chosen when the backup was first set up).
  Lost? -> see FALLBACK at the end.

## 1. Sign in and clone
Sign into GitHub (GitHub Desktop, or browser sign-in for command-line git), then:
    git clone https://github.com/2tml-vn/RPD-song-marker.git D:\rpd
IMPORTANT: clone into exactly D:\rpd — the userscript loads its code from the
project folder via hardcoded file:///D:/rpd/... paths (see step 7). If you
clone somewhere else, you must edit those paths (step 7).
RESTORE.md is inside the clone — every step below comes with it.

## 2. Install tools
    winget install Python.Python.3.12 SecretsOPerationS.SOPS FiloSottile.age aria2
(aria2 is optional — faster downloads; the app falls back to plain yt-dlp
without it. Skip Python via winget if you prefer python.org.)

## 3. Python packages
    pip install -r requirements.txt
(python-dotenv, curl_cffi, aiohttp, shazamio, yt-dlp, pytest)

## 4. Restore the decryption key
The repo's key.age is the age private key, scrambled with the passphrase.
This puts it where sops looks for it:
    mkdir "%APPDATA%\sops\age"
    age -d key.age > "%APPDATA%\sops\age\keys.txt"      <- type the passphrase
(PowerShell: New-Item -ItemType Directory -Force "$env:APPDATA\sops\age")

## 5. Restore the API keys
    sops -d --input-type binary .env.enc > .env
(--input-type binary matters — sops otherwise guesses the format wrong
from the ".enc" extension.)

## 6. One-time Windows setup
Registers the jrpd:// protocol handler the browser panel's Start button uses:
    double-click setup_protocol.bat
(HKCU only, no admin needed, safe to re-run. It embeds the absolute python
path and script path — re-run it if the project folder ever moves.)

## 7. Browser side
Install exactly ONE userscript into Tampermonkey:
    - JRPD Local Link-1.0.user.js
That tiny loader @requires the real code (jrpd_state, jrpd_utils,
jrpd_results, jrpd_songs, jrpd_marker) straight from the
project folder via file:///D:/rpd/... paths. Do NOT install
jrpd_marker.user.js separately — the loader already pulls it in.
Notes:
  - Tampermonkey needs local-file access enabled for this to work
    (browser extensions page > Tampermonkey > "Allow access to file URLs").
  - If you cloned to a path other than D:\rpd, edit the @require file:///
    lines in JRPD Local Link-1.0.user.js to match — they are hardcoded.

## 8. Use it
Open YouTube/Bilibili, click the panel's Start button.
First jrpd:// click: the browser asks for permission — choose "Always allow".
Command-line equivalent:
    python label_marks_complete.py <video_id>
One session at a time — the pipeline serves port 5000.

## Notes
- Verify the keys restored correctly:  python -c "import config"
  (clean exit = good). Full app boot: import server.py's modules or just run
  a real session.
- runs/ audio is NOT in the repo — the app re-downloads it from YouTube by
  video ID as needed; the folder starts empty.
- Editor: Notepad++ at the default path, or set JRPD_EDITOR in .env.
- To reconfirm you still remember the passphrase anytime:
      age -d key.age | findstr "AGE-SECRET-KEY" >nul && echo PASSPHRASE CORRECT

## FALLBACK (passphrase lost)
The encrypted key cannot be recovered — that is the point of the passphrase.
Re-issue ACRCloud credentials at https://console.acrcloud.com, write a fresh
.env, then re-encrypt:
    sops -e --input-type binary --output-type binary .env > .env.enc
