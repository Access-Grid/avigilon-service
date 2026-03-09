"""
Application entry point for AccessGrid Avigilon Unity Agent
"""

import os
import sys
import logging

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from .constants import VERSION
from .gui.app import AccessGridAvigilonGUI
from .utils.logging import configure_logging

logger = configure_logging()
logging.getLogger().setLevel(logging.DEBUG)


def _before_send_filter(event, hint):
    """Strip sensitive fields before shipping to Sentry."""
    if 'extra' in event:
        for key in list(event['extra'].keys()):
            if any(s in key.lower() for s in ('password', 'secret', 'token', 'connection')):
                event['extra'][key] = '[REDACTED]'
    return event


def init_sentry():
    dsn = os.environ.get("SENTRY_DSN", "")
    if not dsn:
        logger.debug("SENTRY_DSN not set — error reporting disabled")
        return
    sentry_logging = LoggingIntegration(
        level=logging.INFO,
        event_level=logging.ERROR,
    )
    sentry_sdk.init(
        dsn=dsn,
        send_default_pii=False,
        traces_sample_rate=0.1,
        environment="production",
        release=f"accessgrid-avigilon-agent@{VERSION}",
        integrations=[sentry_logging],
        before_send=_before_send_filter,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("sentry_sdk").setLevel(logging.WARNING)
    logger.info("Sentry initialized")


def main():
    try:
        init_sentry()
        logger.info(f"Starting AccessGrid Avigilon Unity Agent v{VERSION}")
        app = AccessGridAvigilonGUI()
        app.run()
    except ImportError as e:
        msg = f"Missing dependency: {e}\n\nRun: pip install -r requirements.txt"
        logger.error(msg)
        try:
            from tkinter import messagebox
            messagebox.showerror("Dependency Error", msg)
        except Exception:
            print(msg)
        sys.exit(1)
    except Exception as e:
        msg = f"Fatal error: {e}"
        logger.error(msg, exc_info=True)
        try:
            from tkinter import messagebox
            messagebox.showerror("Fatal Error", f"Application failed to start:\n{e}")
        except Exception:
            print(msg)
        sys.exit(1)
