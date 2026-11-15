# Restoring this project on a new machine

The repo is the complete backup: code, `songs.json`, and the API keys
(`.env` stored encrypted as `.env.enc`). GitHub never holds plaintext secrets.

## 1. Install tools
- git, Python
- sops + age: `winget install SecretsOPerationS.SOPS FiloSottile.age`

## 2. Clone
```
git clone https://github.com/2tml-vn/RPD-song-marker.git
cd RPD-song-marker
```

## 3. Restore the decryption key
The repo contains `key.age` — the age private key, scrambled with a passphrase
(the one chosen at initial setup). Rebuild the key file sops reads by default:
```
mkdir "%APPDATA%\sops\age"          (PowerShell: New-Item -ItemType Directory -Force "$env:APPDATA\sops\age")
age -d key.age > "%APPDATA%\sops\age\keys.txt"
```
Enter the passphrase when prompted.

## 4. Restore the API keys
```
sops -d --input-type binary .env.enc > .env
```
(`--input-type binary` matters — sops otherwise guesses the format from the
`.enc` extension and fails.)

## 5. Verify
```
python -c "import config"
```
Then start the app as usual.

## If the passphrase is lost
The key can't be recovered — that's the point of the passphrase. Fallback:
re-issue ACRCloud credentials at https://console.acrcloud.com and write a
fresh `.env`, then re-encrypt:
```
sops -e --input-type binary --output-type binary .env > .env.enc
```
