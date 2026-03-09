"""
Centralized constants and configuration for AccessGrid Avigilon Unity Agent
"""

import os
import sys

VERSION = "1.0.0"

# Config directory - platform-aware
if sys.platform == 'win32':
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Local", "AccessGridAvigilonAgent")
elif sys.platform == 'darwin':
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "AccessGridAvigilonAgent")
else:
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "accessgrid-avigilon-agent")


def ensure_config_dir():
    """Ensure the config directory exists"""
    os.makedirs(CONFIG_DIR, exist_ok=True)


CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

# Local SQLite database for sync state tracking
# Replaces the ag_credentials table in the Lenel version
# (cannot write to Plasec's database directly)
DB_FILE = os.path.join(CONFIG_DIR, "sync_state.db")

ENCRYPTION_KEY_ENV = "AG_ENCRYPTION_KEY"

# Sync settings
MIN_SYNC_INTERVAL = 30.0          # API polling is slower than SQL scanning
SYNC_INTERVAL_MULTIPLIER = 2
MAX_RETRY_COUNT = 3
ERROR_BACKOFF_SECONDS = 60

# GUI settings
DEFAULT_WINDOW_SIZE = "600x800"
LOG_FILE_NAME = "accessgrid_avigilon_agent.log"

# Plasec identity status codes
PLASEC_IDENTITY_STATUS_ACTIVE = "1"
PLASEC_IDENTITY_STATUS_INACTIVE = "2"

# Plasec token status codes (confirmed from live API)
PLASEC_TOKEN_STATUS_ACTIVE        = "1"   # Active
PLASEC_TOKEN_STATUS_INACTIVE      = "2"   # Inactive
PLASEC_TOKEN_STATUS_NOT_YET_ACTIVE = "3"  # Not yet active
PLASEC_TOKEN_STATUS_EXPIRED       = "4"   # Expired

# Keep alias for backward compat within this codebase
PLASEC_TOKEN_STATUS_LOST = PLASEC_TOKEN_STATUS_INACTIVE

# Plasec token type codes
PLASEC_TOKEN_TYPE_STANDARD = "0"      # Standard proximity/smartcard

# Mapping from Plasec token status to AccessGrid state
PLASEC_TO_AG_STATUS = {
    "1": "active",
    "2": "suspended",
    "3": "suspended",   # Not yet active → treat as suspended in AG
    "4": "suspended",   # Expired → treat as suspended in AG
}

# Mapping from AccessGrid state to Plasec token status
AG_TO_PLASEC_STATUS = {
    "active": "1",
    "suspended": "2",
    "created": "1",
}

# Photo processing settings
MAX_PHOTO_SIZE_MB = 5
MAX_PHOTO_SIZE_KB = 200
PHOTO_MAX_DIMENSIONS = (1242, 1242)
PHOTO_JPEG_QUALITY = 85

# HTTP request settings
HTTP_TIMEOUT = 30           # seconds
HTTP_USER_AGENT = "AccessGrid-Avigilon-Agent/1.0"
