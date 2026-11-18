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
# Shazamio-style retry ladder: retriable statuses (429/5xx) are re-sent
# with exponential waits: base_wait * 2^attempt (with jitter), up to
# AHA_RETRY_ATTEMPTS total attempts.
def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


AHA_CONFIG = {
    'url': os.getenv('AHA_URL', 'https://aha-music.com/identify'),
    'timeout': _env_int('AHA_TIMEOUT', 30),
    # Separate connect-stage budget (seconds) for diagnostics: with a single
    # total timeout, a connect-stage blackhole (curl 7) is indistinguishable
    # from a response-stage stall (curl 28, 0 bytes). Tuple timeouts let us
    # classify where the endpoint wedged.
    'connect_timeout': _env_int('AHA_CONNECT_TIMEOUT', 8),
    'enabled': os.getenv('AHA_ENABLED', '1').strip().lower()
    not in ('0', 'false', 'no', 'off', ''),
    'retry_attempts': _env_int('AHA_RETRY_ATTEMPTS', 5),
    'retry_base_wait': _env_float('AHA_RETRY_BASE_WAIT', 0.5),
}

# --- Display Format ---
# Variables: {ori_song}, {int_song}, {info}, {ori_artist}, {int_artist}
# Sections in [...] are optional: only included if all variables inside have values.
DISPLAY_FORMAT = "{ori_song}[ ({int_song})][ ({info})] - {ori_artist}[ ({int_artist})]"

# --- File Paths ---
BASE_DIR = Path(__file__).parent
SONG_OVERRIDES_FILE = BASE_DIR / "songs.json"
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
    # Keep the logger at DEBUG: the file handler wants every record
    # (including [AHA] stall/retry diagnostics), and the console handler
    # below still filters at JRPD_LOG_LEVEL (default INFO). Previously the
    # logger's own INFO level killed DEBUG records before any handler was
    # consulted, so even logs/jrpd.log was blind to them.
    logger = logging.getLogger("JRPD")
    logger.setLevel(logging.DEBUG)

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

        # Console handler — follows JRPD_LOG_LEVEL (default INFO)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))

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
