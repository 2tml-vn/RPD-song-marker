"""
Configuration constants and file paths for JRPD marker system.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# --- Network Configuration ---
PORT = 5000

# --- ACRCloud Configuration ---
# Credentials are loaded from .env file via environment variables
ACR_CONFIG = {
    'host': os.getenv('ACR_HOST', 'identify-ap-southeast-1.acrcloud.com'),
    'access_key': os.getenv('ACR_ACCESS_KEY'),
    'access_secret': os.getenv('ACR_ACCESS_SECRET'),
}

# --- AHA Music Configuration ---
# Public unauthenticated endpoint (fronts the same ACRCloud fingerprint DB).
# AHA_ENABLED=0 disables the AHA fallback; AHA_TIMEOUT sets seconds.
def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


AHA_CONFIG = {
    'url': os.getenv('AHA_URL', 'https://aha-music.com/identify'),
    'timeout': _env_int('AHA_TIMEOUT', 30),
    'enabled': os.getenv('AHA_ENABLED', '1').strip().lower()
    not in ('0', 'false', 'no', 'off', ''),
}

# --- Display Format ---
# Variables: {ori_song}, {int_song}, {info}, {ori_artist}, {int_artist}
# Sections in [...] are optional: only included if all variables inside have values.
DISPLAY_FORMAT = "{ori_song}[ ({int_song})][ ({info})] - {ori_artist}[ ({int_artist})]"

# --- File Paths ---
BASE_DIR = Path(__file__).parent
SONG_OVERRIDES_FILE = BASE_DIR / "songs.json"
WRONG_MATCHES_FILE = BASE_DIR / "wrong_matches.json"
MISSED_SONGS_FILE = BASE_DIR / "missed_songs.json"
MISIDENTIFIED_SONGS_FILE = BASE_DIR / "misidentified_songs.json"
SONG_NAME_PARENS_EXCEPTIONS_FILE = BASE_DIR / "song_name_parentheses_exceptions.json"
RUNS_DIR = BASE_DIR / "runs"

# --- Logging Configuration ---
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "jrpd.log"
LOG_LEVEL = os.getenv('JRPD_LOG_LEVEL', 'INFO')

# --- Editor Configuration ---
# Path to text editor for opening results (defaults to Notepad++ on Windows)
EDITOR_PATH = os.getenv('JRPD_EDITOR', r'C:\Program Files\Notepad++\notepad++.exe')

# --- Runtime State (mutable via class) ---
class RuntimeState:
    """Container for runtime-modifiable state."""
    VIDEO_ID = "default"


# Global instance - other modules import this
runtime = RuntimeState()


def setup_logging():
    """
    Configure logging for the JRPD application.
    Creates log directory if it doesn't exist.
    """
    import logging
    from logging.handlers import RotatingFileHandler

    # Ensure log directory exists
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Clear previous run's log file for fresh start
    if LOG_FILE.exists():
        LOG_FILE.unlink()

    # Create root logger
    logger = logging.getLogger("JRPD")
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

    # Prevent duplicate handlers
    if not logger.handlers:
        # File handler with rotation (10MB max, 5 backups)
        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Add handlers
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger
