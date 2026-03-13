"""
Main GUI application for AccessGrid Avigilon Unity Agent
"""

import tkinter as tk
import threading
from tkinter import ttk, messagebox
import logging
import sys
import os
from datetime import datetime
from typing import Optional, Dict

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    from accessgrid import AccessGrid, AccessGridError
except ImportError:
    class AccessGrid:
        def __init__(self, *args, **kwargs): pass
    class AccessGridError(Exception): pass

from ..constants import VERSION, DEFAULT_WINDOW_SIZE, DB_FILE
from ..config import EncryptionManager, load_config, save_config, validate_config
from ..api.client import PlaSecClient
from ..sync.local_db import LocalDB
from ..sync.engine import SyncEngine
from ..utils.logging import configure_logging, setup_gui_logging
from ..utils.networking import check_internet_connectivity
from .dialogs import PlaSecConfigDialog, AccessGridConfigDialog

logger = logging.getLogger(__name__)

# Status indicator colours
COLOR_OK      = "#27ae60"   # green
COLOR_WARN    = "#f39c12"   # amber
COLOR_ERR     = "#e74c3c"   # red
COLOR_IDLE    = "#95a5a6"   # grey


class AccessGridAvigilonGUI:
    """Main application window for the Avigilon Unity / Plasec sync agent."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"AccessGrid Avigilon Agent v{VERSION}")
        self.root.geometry(DEFAULT_WINDOW_SIZE)
        self.root.resizable(True, True)
        self.root.minsize(560, 700)

        # Set app icon
        try:
            icon_path = os.path.join(os.path.dirname(__file__), '..', '..', 'assets', 'logo.png')
            icon_img = tk.PhotoImage(file=os.path.abspath(icon_path))
            self.root.iconphoto(True, icon_img)
            self._icon_img = icon_img  # prevent garbage collection
        except Exception:
            pass

        self.encryption   = EncryptionManager()
        self.config: Optional[Dict] = load_config(self.encryption)

        self.plasec_client: Optional[PlaSecClient] = None
        self.ag_client:     Optional[AccessGrid]   = None
        self.local_db:      Optional[LocalDB]      = None
        self.sync_engine:   Optional[SyncEngine]   = None

        # UI state variables
        self.plasec_status_var = tk.StringVar(value="Not connected")
        self.ag_status_var     = tk.StringVar(value="Not connected")
        self.sync_status_var   = tk.StringVar(value="Stopped")
        self.last_sync_var     = tk.StringVar(value="Never")
        self.error_count_var   = tk.StringVar(value="0")
        self.interval_var      = tk.StringVar(value="–")

        self._build_ui()
        self._apply_logo()

        # Auto-connect if config is already saved
        if self.config and validate_config(self.config):
            self.root.after(500, self._auto_connect)

        # Periodic UI refresh
        self._schedule_status_refresh()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ---- Menu bar ----
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Configure Plasec Server…",  command=self._open_plasec_dialog)
        file_menu.add_command(label="Configure AccessGrid API…", command=self._open_ag_dialog)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ---- Top frame: logo + title ----
        top_frame = ttk.Frame(self.root, padding=(16, 12, 16, 4))
        top_frame.pack(fill=tk.X)

        self.logo_label = ttk.Label(top_frame)
        self.logo_label.pack(side=tk.LEFT)

        title_frame = ttk.Frame(top_frame)
        title_frame.pack(side=tk.LEFT, padx=12)
        ttk.Label(
            title_frame,
            text="AccessGrid Avigilon Agent",
            font=('Arial', 16, 'bold'),
        ).pack(anchor=tk.W)
        ttk.Label(
            title_frame,
            text="Plasec / Avigilon Unity ↔ AccessGrid Mobile Credentials",
            font=('Arial', 9),
            foreground='gray',
        ).pack(anchor=tk.W)

        ttk.Separator(self.root, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=16)

        # ---- Status cards ----
        status_outer = ttk.Frame(self.root, padding=(16, 10))
        status_outer.pack(fill=tk.X)
        status_outer.columnconfigure(0, weight=1)
        status_outer.columnconfigure(1, weight=1)

        self._status_card(status_outer, "Plasec Server",  self.plasec_status_var, 0)
        self._status_card(status_outer, "AccessGrid API", self.ag_status_var,     1)

        # ---- Sync info row ----
        sync_frame = ttk.LabelFrame(self.root, text="Sync Status", padding=(16, 8))
        sync_frame.pack(fill=tk.X, padx=16, pady=(4, 8))
        sync_frame.columnconfigure(1, weight=1)
        sync_frame.columnconfigure(3, weight=1)

        def srow(label, var, col_label, col_val):
            ttk.Label(sync_frame, text=label, font=('Arial', 9, 'bold')).grid(
                row=0, column=col_label, sticky=tk.W, padx=(0, 4))
            ttk.Label(sync_frame, textvariable=var, font=('Arial', 9)).grid(
                row=0, column=col_val, sticky=tk.W, padx=(0, 20))

        ttk.Label(sync_frame, text="Status:", font=('Arial', 9, 'bold')).grid(
            row=0, column=0, sticky=tk.W, padx=(0, 4))
        ttk.Label(sync_frame, textvariable=self.sync_status_var, font=('Arial', 9)).grid(
            row=0, column=1, sticky=tk.W, padx=(0, 20))

        ttk.Label(sync_frame, text="Last sync:", font=('Arial', 9, 'bold')).grid(
            row=0, column=2, sticky=tk.W, padx=(0, 4))
        ttk.Label(sync_frame, textvariable=self.last_sync_var, font=('Arial', 9)).grid(
            row=0, column=3, sticky=tk.W, padx=(0, 20))

        ttk.Label(sync_frame, text="Errors:", font=('Arial', 9, 'bold')).grid(
            row=0, column=4, sticky=tk.W, padx=(0, 4))
        ttk.Label(sync_frame, textvariable=self.error_count_var, font=('Arial', 9)).grid(
            row=0, column=5, sticky=tk.W, padx=(0, 20))

        ttk.Label(sync_frame, text="Interval:", font=('Arial', 9, 'bold')).grid(
            row=0, column=6, sticky=tk.W, padx=(0, 4))
        ttk.Label(sync_frame, textvariable=self.interval_var, font=('Arial', 9)).grid(
            row=0, column=7, sticky=tk.W)

        # ---- Control buttons ----
        btn_frame = ttk.Frame(self.root, padding=(16, 0, 16, 8))
        btn_frame.pack(fill=tk.X)

        self.start_btn = ttk.Button(
            btn_frame, text="Start Sync", command=self._start_sync, width=14
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 6))

        self.stop_btn = ttk.Button(
            btn_frame, text="Stop Sync", command=self._stop_sync, width=14, state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(
            btn_frame, text="Force Sync Now", command=self._force_sync, width=16
        ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(
            btn_frame, text="Plasec Settings…", command=self._open_plasec_dialog
        ).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(
            btn_frame, text="AG Settings…", command=self._open_ag_dialog
        ).pack(side=tk.RIGHT, padx=(6, 0))

        # ---- Notebook: Logs + Stats ----
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

        # Logs tab
        log_frame = ttk.Frame(self.notebook)
        self.notebook.add(log_frame, text="Logs")
        self.log_text = tk.Text(
            log_frame, wrap=tk.NONE, font=('Courier', 9),
            state=tk.NORMAL, bg='#1e1e1e', fg='#d4d4d4',
        )
        log_scroll_y = ttk.Scrollbar(log_frame, orient=tk.VERTICAL,   command=self.log_text.yview)
        log_scroll_x = ttk.Scrollbar(log_frame, orient=tk.HORIZONTAL, command=self.log_text.xview)
        self.log_text.configure(yscrollcommand=log_scroll_y.set, xscrollcommand=log_scroll_x.set)
        log_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        log_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Stats tab
        stats_frame = ttk.Frame(self.notebook, padding=16)
        self.notebook.add(stats_frame, text="Stats")
        self.stats_text = tk.Text(
            stats_frame, wrap=tk.WORD, font=('Arial', 10),
            state=tk.DISABLED, height=20,
        )
        self.stats_text.pack(fill=tk.BOTH, expand=True)

        # Wire up log handler
        setup_gui_logging(self.log_text)

    def _status_card(self, parent, title: str, var: tk.StringVar, col: int):
        card = ttk.LabelFrame(parent, text=title, padding=(12, 8))
        card.grid(row=0, column=col, sticky=tk.EW, padx=(0 if col == 0 else 6, 0))
        ttk.Label(card, textvariable=var, font=('Arial', 9)).pack(anchor=tk.W)

    def _apply_logo(self):
        """Load logo from assets/logo.png if present."""
        logo_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            'assets', 'logo.png'
        )
        if PIL_AVAILABLE and os.path.exists(logo_path):
            try:
                img = Image.open(logo_path).resize((48, 48), Image.Resampling.LANCZOS)
                self._logo_img = ImageTk.PhotoImage(img)
                self.logo_label.configure(image=self._logo_img)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _auto_connect(self):
        """Silently attempt to connect using saved config on startup."""
        if not self.config:
            return
        threading.Thread(target=self._connect_all, daemon=True).start()

    def _connect_all(self):
        """Connect to both Plasec and AccessGrid (runs in background thread)."""
        self._connect_plasec()
        self._connect_accessgrid()

    def _connect_plasec(self):
        if not self.config or 'plasec' not in self.config:
            return
        pc = self.config['plasec']
        try:
            client = PlaSecClient(
                host=pc['host'],
                username=pc['username'],
                password=pc['password'],
                verify_ssl=False,
            )
            if client.test_connection():
                self.plasec_client = client
                self.plasec_status_var.set(f"Connected ({pc['host']})")
                logger.info(f"Connected to Plasec at {pc['host']}")
            else:
                self.plasec_status_var.set("Auth failed")
                logger.error("Plasec auth failed")
        except Exception as e:
            self.plasec_status_var.set(f"Error: {str(e)[:40]}")
            logger.error(f"Plasec connection error: {e}")

    def _connect_accessgrid(self):
        if not self.config or 'accessgrid' not in self.config:
            return
        ag = self.config['accessgrid']
        try:
            client = AccessGrid(ag['account_id'], ag['api_secret'])
            # Verify by listing cards
            client.access_cards.list(template_id=ag['template_id'])
            self.ag_client = client
            self.ag_status_var.set("Connected")
            logger.info("Connected to AccessGrid API")
        except AccessGridError as e:
            self.ag_status_var.set(f"API error: {str(e)[:40]}")
            logger.error(f"AccessGrid API error: {e}")
        except Exception as e:
            self.ag_status_var.set(f"Error: {str(e)[:40]}")
            logger.error(f"AccessGrid connection error: {e}")

    # ------------------------------------------------------------------
    # Sync control
    # ------------------------------------------------------------------

    def _start_sync(self):
        if not self.config or not validate_config(self.config):
            messagebox.showerror(
                "Configuration Required",
                "Please configure both Plasec and AccessGrid settings first."
            )
            return

        self.start_btn.config(state=tk.DISABLED)
        self.sync_status_var.set("Connecting…")
        threading.Thread(target=self._start_sync_worker, daemon=True).start()

    def _start_sync_worker(self):
        """Run connection + engine startup off the main thread."""
        if not self.plasec_client:
            self._connect_plasec()
        if not self.ag_client:
            self._connect_accessgrid()

        if not self.plasec_client:
            self.root.after(0, lambda: [
                messagebox.showerror("Not Connected", "Cannot connect to Plasec server."),
                self.start_btn.config(state=tk.NORMAL),
                self.sync_status_var.set("Stopped"),
            ])
            return
        if not self.ag_client:
            self.root.after(0, lambda: [
                messagebox.showerror("Not Connected", "Cannot connect to AccessGrid API."),
                self.start_btn.config(state=tk.NORMAL),
                self.sync_status_var.set("Stopped"),
            ])
            return

        try:
            self.local_db = LocalDB(DB_FILE)
            self.local_db.connect()
            self.local_db.ensure_table()

            self.sync_engine = SyncEngine(
                plasec_client=self.plasec_client,
                local_db=self.local_db,
                ag_client=self.ag_client,
                config=self.config,
            )
            self.sync_engine.start()
            logger.info("Sync engine started")

            self.root.after(0, lambda: [
                self.sync_status_var.set("Running"),
                self.start_btn.config(state=tk.DISABLED),
                self.stop_btn.config(state=tk.NORMAL),
            ])

        except Exception as e:
            logger.error(f"Failed to start sync engine: {e}", exc_info=True)
            self.root.after(0, lambda: [
                messagebox.showerror("Start Failed", str(e)),
                self.start_btn.config(state=tk.NORMAL),
                self.sync_status_var.set("Stopped"),
            ])

    def _stop_sync(self):
        if self.sync_engine:
            self.sync_engine.stop()
            self.sync_engine = None
        if self.local_db:
            self.local_db.close()
            self.local_db = None

        self.sync_status_var.set("Stopped")
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        logger.info("Sync engine stopped")

    def _force_sync(self):
        if not self.sync_engine or not self.sync_engine.running:
            messagebox.showwarning("Not Running", "Start the sync engine first.")
            return
        threading.Thread(target=self.sync_engine.force_sync, daemon=True).start()
        logger.info("Manual sync triggered")

    # ------------------------------------------------------------------
    # Config dialogs
    # ------------------------------------------------------------------

    def _open_plasec_dialog(self):
        dialog = PlaSecConfigDialog(self.root, self.config)
        if dialog.result:
            if not self.config:
                self.config = {}
            self.config['plasec'] = dialog.result
            save_config(self.config, self.encryption)
            # Reset connection so next action re-connects with new creds
            self.plasec_client = None
            self.plasec_status_var.set("Reconnecting…")
            threading.Thread(target=self._connect_plasec, daemon=True).start()

    def _open_ag_dialog(self):
        dialog = AccessGridConfigDialog(self.root, self.config)
        if dialog.result:
            if not self.config:
                self.config = {}
            self.config['accessgrid'] = dialog.result
            save_config(self.config, self.encryption)
            self.ag_client = None
            self.ag_status_var.set("Reconnecting…")
            threading.Thread(target=self._connect_accessgrid, daemon=True).start()

    # ------------------------------------------------------------------
    # Periodic status refresh
    # ------------------------------------------------------------------

    def _schedule_status_refresh(self):
        self.root.after(3000, self._refresh_status)

    def _refresh_status(self):
        if self.sync_engine:
            status = self.sync_engine.get_status()
            self.sync_status_var.set("Running" if status['running'] else "Stopped")
            last = status.get('last_sync_time')
            self.last_sync_var.set(
                last.strftime('%H:%M:%S') if last else "Never"
            )
            self.error_count_var.set(str(status.get('error_count', 0)))
            interval = status.get('sync_interval')
            self.interval_var.set(f"{interval:.0f}s" if interval else "–")
        self._schedule_status_refresh()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _on_close(self):
        if self.sync_engine and self.sync_engine.running:
            if not messagebox.askokcancel(
                "Quit",
                "IF YOU QUIT THIS APP, CREDENTIALS WILL NO LONGER "
                "SYNCHRONIZE BETWEEN AVIGILON AND ACCESSGRID.\n\n"
                "Click OK if you're sure this is what you want to do."
            ):
                return
        self._stop_sync()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
