"""
Configuration management and encryption for AccessGrid Avigilon Unity Agent
"""

import json
import os
import logging
import hashlib
import base64
from typing import Dict, Optional
from tkinter import messagebox

from cryptography.fernet import Fernet, InvalidToken

from .constants import CONFIG_FILE, ENCRYPTION_KEY_ENV, ensure_config_dir, CONFIG_DIR

logger = logging.getLogger(__name__)

_KEY_FILE = os.path.join(CONFIG_DIR, '.agent_key')


class EncryptionManager:
    """
    Encrypts/decrypts sensitive config values using Fernet (AES-128-CBC + HMAC-SHA256).

    Key resolution order:
      1. AG_ENCRYPTION_KEY environment variable (SHA-256 hashed to 32 bytes, then
         base64url-encoded to produce a valid Fernet key).
      2. A randomly generated key stored in <config_dir>/.agent_key (created on
         first run, permissions set to 0o600).  This ensures each installation
         has a unique key even without explicit configuration.
    """

    def __init__(self):
        env_key = os.environ.get(ENCRYPTION_KEY_ENV)
        if env_key:
            # Derive a valid Fernet key (32 raw bytes, base64url-encoded) from
            # the user-supplied string so any passphrase works.
            key_bytes = hashlib.sha256(env_key.encode()).digest()
            fernet_key = base64.urlsafe_b64encode(key_bytes)
        else:
            fernet_key = self._get_or_create_machine_key()
        self._fernet = Fernet(fernet_key)

    @staticmethod
    def _get_or_create_machine_key() -> bytes:
        """Return the persisted per-machine key, generating one if absent."""
        ensure_config_dir()
        if os.path.exists(_KEY_FILE):
            with open(_KEY_FILE, 'rb') as f:
                return f.read().strip()
        key = Fernet.generate_key()
        with open(_KEY_FILE, 'wb') as f:
            f.write(key)
        try:
            os.chmod(_KEY_FILE, 0o600)
        except OSError:
            pass
        logger.info("Generated new per-machine encryption key")
        return key

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, Exception):
            # Ciphertext from a different key or old XOR-encoded config —
            # return as-is so the caller sees an auth failure rather than a crash.
            logger.warning("Failed to decrypt config value — re-enter credentials")
            return ciphertext


def load_config(encryption_manager: EncryptionManager) -> Optional[Dict]:
    """Load configuration from encrypted file"""
    ensure_config_dir()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                encrypted_config = json.load(f)

            config = {
                'plasec': {
                    'host':     encryption_manager.decrypt(encrypted_config['plasec']['host']),
                    'username': encryption_manager.decrypt(encrypted_config['plasec']['username']),
                    'password': encryption_manager.decrypt(encrypted_config['plasec']['password']),
                },
                'accessgrid': {
                    'account_id': encryption_manager.decrypt(encrypted_config['accessgrid']['account_id']),
                    'api_secret': encryption_manager.decrypt(encrypted_config['accessgrid']['api_secret']),
                    'template_id': encryption_manager.decrypt(encrypted_config['accessgrid']['template_id']),
                },
            }
            return config
        except Exception as e:
            logger.error(f"Failed to load config: {str(e)}")
            return None
    return None


def save_config(config_data: Dict, encryption_manager: EncryptionManager) -> bool:
    """
    Save configuration to encrypted file.

    Only the sections present in config_data are written; sections already on
    disk but absent from config_data are preserved.  This allows the Plasec and
    AccessGrid dialogs to be saved independently without losing each other's data.
    """
    try:
        ensure_config_dir()

        # Preserve any sections already saved that aren't being updated
        encrypted_config: Dict = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    encrypted_config = json.load(f)
            except Exception:
                encrypted_config = {}

        if 'plasec' in config_data:
            encrypted_config['plasec'] = {
                'host':     encryption_manager.encrypt(config_data['plasec']['host']),
                'username': encryption_manager.encrypt(config_data['plasec']['username']),
                'password': encryption_manager.encrypt(config_data['plasec']['password']),
            }

        if 'accessgrid' in config_data:
            encrypted_config['accessgrid'] = {
                'account_id':  encryption_manager.encrypt(config_data['accessgrid']['account_id']),
                'api_secret':  encryption_manager.encrypt(config_data['accessgrid']['api_secret']),
                'template_id': encryption_manager.encrypt(config_data['accessgrid']['template_id']),
            }

        with open(CONFIG_FILE, 'w') as f:
            json.dump(encrypted_config, f, indent=2)

        logger.info("Configuration saved successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to save config: {str(e)}")
        try:
            messagebox.showerror("Error", f"Failed to save config: {str(e)}")
        except Exception:
            pass
        return False


def validate_config(config: Dict) -> bool:
    """Validate configuration structure and required fields"""
    try:
        plasec_config = config.get('plasec', {})
        required_plasec_fields = ['host', 'username', 'password']
        for field in required_plasec_fields:
            if not plasec_config.get(field):
                logger.error(f"Missing required Plasec field: {field}")
                return False

        ag_config = config.get('accessgrid', {})
        required_ag_fields = ['account_id', 'api_secret', 'template_id']
        for field in required_ag_fields:
            if not ag_config.get(field):
                logger.error(f"Missing required AccessGrid field: {field}")
                return False

        return True
    except Exception as e:
        logger.error(f"Config validation error: {str(e)}")
        return False
