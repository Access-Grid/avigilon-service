"""
Logging configuration for AccessGrid Avigilon Unity Agent
"""

import logging
import logging.handlers
import tkinter as tk
import os

from ..constants import LOG_FILE_NAME, CONFIG_DIR


def configure_logging(log_level: str = "INFO") -> logging.Logger:
    """Configure file + console logging."""
    logger = logging.getLogger('AccessGridAvigilonAgent')
    logger.setLevel(getattr(logging, log_level.upper()))
    logger.handlers.clear()

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    os.makedirs(CONFIG_DIR, exist_ok=True)
    log_path = os.path.join(CONFIG_DIR, LOG_FILE_NAME)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=5
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


class GUILogHandler(logging.Handler):
    """Sends log records to a Tkinter Text widget."""

    def __init__(self, text_widget: tk.Text):
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.text_widget.after(0, self._update_gui, msg)
        except Exception:
            self.handleError(record)

    def _update_gui(self, message: str):
        try:
            self.text_widget.insert(tk.END, message + '\n')
            self.text_widget.see(tk.END)
            lines = self.text_widget.get('1.0', tk.END).split('\n')
            if len(lines) > 1000:
                self.text_widget.delete('1.0', f'{len(lines) - 1000}.0')
        except Exception:
            pass


def setup_gui_logging(text_widget: tk.Text, log_level: str = "DEBUG") -> logging.Logger:
    logger = logging.getLogger()
    gui_handler = GUILogHandler(text_widget)
    gui_handler.setLevel(getattr(logging, log_level.upper()))
    logger.addHandler(gui_handler)
    return logger
