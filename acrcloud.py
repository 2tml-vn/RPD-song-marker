"""
ACRCloud integration for JRPD marker system.
Provides audio fingerprinting and song identification via ACRCloud API.
"""
import asyncio
import aiohttp
import os
import time
import hashlib
import hmac
import base64
import json
import re
import logging
from typing import Optional, Dict, Any

from config import ACR_CONFIG

logger = logging.getLogger("JRPD")

# ACRCloud API endpoint
ENDPOINT = '/v1/identify'

# Module-level session for connection pooling (reused across requests)
_acr_session: Optional[aiohttp.ClientSession] = None


def is_japanese(text):
    """
    Checks if a string contains Japanese characters (Hiragana, Katakana, or Kanji).
    """
    if not text: return False
    return bool(re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text))


async def get_acr_session() -> aiohttp.ClientSession:
    """
    Get or create the shared ACRCloud aiohttp session.
    Reuses the session for connection pooling efficiency.
    """
    global _acr_session
    if _acr_session is None or _acr_session.closed:
        _acr_session = aiohttp.ClientSession()
    return _acr_session


async def close_acr_session():
    """Close the ACRCloud session (call on shutdown)."""
    global _acr_session
    if _acr_session and not _acr_session.closed:
        await _acr_session.close()
        _acr_session = None


async def recognize(file_path, access_key=None, access_secret=None, host=None) -> Optional[Dict[str, Any]]:
    """
    Identifies audio using ACRCloud's REST API.
    Returns a dict with 'title', 'en_title', 'artist' or None if not found.
    """
    key = access_key or ACR_CONFIG.get('access_key')
    secret = access_secret or ACR_CONFIG.get('access_secret')
    acr_host = host or ACR_CONFIG.get('host')

    # Check for missing credentials - return early
    if not key or not secret:
        logger.warning("[ACR] Missing ACRCloud credentials - check .env file")
        return None

    # Check for placeholder keys - return early
    if key == 'your-access-key-here' or key == 'YOUR_ACCESS_KEY':
        logger.warning("[ACR] Placeholder access key detected, skipping identification")
        return None

    http_method = "POST"
    http_uri = ENDPOINT
    data_type = "audio"
    signature_version = "1"
    timestamp = str(int(time.time()))

    string_to_sign = f"{http_method}\n{http_uri}\n{key}\n{data_type}\n{signature_version}\n{timestamp}"

    sign = hmac.new(secret.encode('ascii'), string_to_sign.encode('ascii'), digestmod=hashlib.sha1).digest()
    signature = base64.b64encode(sign).decode('ascii')

    url = f"http://{acr_host}{ENDPOINT}"

    try:
        session = await get_acr_session()
        
        # Read file content BEFORE the async request to avoid "I/O operation on closed file"
        file_size = os.path.getsize(file_path)
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        logger.debug(f"[ACR] Sending request to {url}, file size: {file_size} bytes")
        
        # Build multipart form data properly
        data = aiohttp.FormData()
        data.add_field('sample', file_content, filename='audio_sample.wav')
        data.add_field('sample_bytes', str(file_size))
        data.add_field('access_key', key)
        data.add_field('data_type', data_type)
        data.add_field('signature_version', signature_version)
        data.add_field('signature', signature)
        data.add_field('timestamp', timestamp)

        async with session.post(url, data=data) as response:
            res_text = await response.text()
            logger.debug(f"[ACR] Response status: {response.status}")
            logger.debug(f"[ACR] Response text: {res_text[:500] if res_text else '(empty)'}")
            
            result = json.loads(res_text)

            status = result.get('status', {})
            status_code = status.get('code', -1)
            logger.debug(f"[ACR] Status code: {status_code}, msg: {status.get('msg', 'unknown')}")
            
            if status_code == 0:
                metadata = result.get('metadata', {})
                music = metadata.get('music', [{}])[0]

                main_title = music.get('title')
                if not main_title or main_title == 'Unknown Title':
                    # If we don't even have a main title, this is a failed identification
                    return None

                ext = music.get('external_metadata', {})

                # Try to find an English title in external metadata (Spotify/Deezer)
                en_title = None
                for source in ['spotify', 'deezer']:
                    source_data = ext.get(source, {})
                    t = source_data.get('track', {}).get('name')
                    if t and not is_japanese(t):
                        en_title = t
                        break

                artist_list = music.get('artists', [])
                if not artist_list:
                    return None

                artist = ", ".join([a.get('name') for a in artist_list])

                if not main_title or not artist or artist.strip() == "":
                    return None

                return {
                    "title": main_title,
                    "en_title": en_title,
                    "artist": artist
                }
    except aiohttp.ClientError as e:
        logger.debug(f"[ACR] Network error: {e}")
    except json.JSONDecodeError as e:
        logger.debug(f"[ACR] JSON decode error: {e}")
    except OSError as e:
        logger.debug(f"[ACR] File error: {e}")
    except Exception as e:
        logger.debug(f"[ACR] Unexpected error: {e}")
    return None