"""
Configuration dialogs for AccessGrid Avigilon Unity Agent
"""

import tkinter as tk
from tkinter import ttk, messagebox
from typing import Optional, Dict

from ..api.client import PlaSecClient, PlaSecAuthError
from ..utils.networking import check_internet_connectivity, test_plasec_connectivity

try:
    from accessgrid import AccessGrid, AccessGridError
except ImportError:
    class AccessGrid:
        def __init__(self, *args, **kwargs): pass
    class AccessGridError(Exception): pass


class PlaSecConfigDialog:
    """
    Dialog for configuring the Plasec / Avigilon Unity server connection.

    Replaces DatabaseConfigDialog from lenel-onguard-service.
    Fields: host, username, password, verify_ssl (bool), group_id (optional filter).
    """

    def __init__(self, parent, current_config: Optional[Dict] = None):
        self.result = None

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Plasec / Avigilon Unity Configuration")
        self.dialog.geometry("520x300")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth()  // 2) - 260
        y = (self.dialog.winfo_screenheight() // 2) - 150
        self.dialog.geometry(f"520x300+{x}+{y}")

        # Variables
        self.host     = tk.StringVar()
        self.username = tk.StringVar()
        self.password = tk.StringVar()

        if current_config and 'plasec' in current_config:
            pc = current_config['plasec']
            self.host.set(pc.get('host', ''))
            self.username.set(pc.get('username', ''))
            self.password.set(pc.get('password', ''))

        self._build_ui()
        self.dialog.wait_window()

    def _build_ui(self):
        main = ttk.Frame(self.dialog, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            main, text="Plasec / Avigilon Unity Server", font=('Arial', 13, 'bold')
        ).pack(pady=(0, 16))

        form = ttk.Frame(main)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        def row(label, widget, r):
            ttk.Label(form, text=label).grid(row=r, column=0, sticky=tk.W, pady=6)
            widget.grid(row=r, column=1, sticky=tk.EW, pady=6, padx=(12, 0))

        row("Host / IP:",
            ttk.Entry(form, textvariable=self.host, width=34), 0)
        row("Username:",
            ttk.Entry(form, textvariable=self.username, width=34), 1)
        row("Password:",
            ttk.Entry(form, textvariable=self.password, show="*", width=34), 2)

        btns = ttk.Frame(main)
        btns.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(btns, text="Test Connection", command=self._test).pack(side=tk.LEFT)
        ttk.Button(btns, text="Cancel", command=self.dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="OK", command=self._ok).pack(side=tk.RIGHT, padx=(0, 8))

    def _validate(self) -> bool:
        for val, name in [
            (self.host.get(), "Host / IP"),
            (self.username.get(), "Username"),
            (self.password.get(), "Password"),
        ]:
            if not val.strip():
                messagebox.showerror("Validation Error", f"{name} is required")
                return False
        return True

    def _test(self):
        if not self._validate():
            return

        host = self.host.get().strip()

        # 1. TCP reachability
        ok, msg = test_plasec_connectivity(host)
        if not ok:
            messagebox.showerror("Connection Failed", f"Network test failed:\n{msg}")
            return

        # 2. Auth test
        try:
            client = PlaSecClient(
                host=host,
                username=self.username.get().strip(),
                password=self.password.get().strip(),
                verify_ssl=False,
            )
            if client.test_connection():
                messagebox.showinfo(
                    "Success",
                    f"Connected to Plasec at {host}\nAuthentication successful."
                )
            else:
                messagebox.showerror(
                    "Auth Failed",
                    "Reached the server but authentication failed.\n"
                    "Check username and password."
                )
        except PlaSecAuthError as e:
            messagebox.showerror("Auth Failed", str(e))
        except Exception as e:
            messagebox.showerror("Connection Failed", str(e))

    def _ok(self):
        if not self._validate():
            return
        self.result = {
            'host':     self.host.get().strip(),
            'username': self.username.get().strip(),
            'password': self.password.get().strip(),
        }
        self.dialog.destroy()


class AccessGridConfigDialog:
    """AccessGrid API configuration dialog (unchanged from lenel-onguard-service)."""

    def __init__(self, parent, current_config: Optional[Dict] = None):
        self.result = None

        self.dialog = tk.Toplevel(parent)
        self.dialog.title("AccessGrid Configuration")
        self.dialog.geometry("500x300")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        self.dialog.grab_set()

        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth()  // 2) - 250
        y = (self.dialog.winfo_screenheight() // 2) - 150
        self.dialog.geometry(f"500x300+{x}+{y}")

        self.account_id  = tk.StringVar()
        self.api_secret  = tk.StringVar()
        self.template_id = tk.StringVar()

        if current_config and 'accessgrid' in current_config:
            ag = current_config['accessgrid']
            self.account_id.set(ag.get('account_id', ''))
            self.api_secret.set(ag.get('api_secret', ''))
            self.template_id.set(ag.get('template_id', ''))

        self._build_ui()
        self.dialog.wait_window()

    def _build_ui(self):
        main = ttk.Frame(self.dialog, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text="AccessGrid Configuration", font=('Arial', 13, 'bold')).pack(pady=(0, 16))

        form = ttk.Frame(main)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Account ID:").grid(row=0, column=0, sticky=tk.W, pady=10)
        ttk.Entry(form, textvariable=self.account_id, width=40).grid(
            row=0, column=1, sticky=tk.EW, pady=10, padx=(12, 0))

        ttk.Label(form, text="API Secret:").grid(row=1, column=0, sticky=tk.W, pady=10)
        ttk.Entry(form, textvariable=self.api_secret, show="*", width=40).grid(
            row=1, column=1, sticky=tk.EW, pady=10, padx=(12, 0))

        ttk.Label(form, text="Template ID:").grid(row=2, column=0, sticky=tk.W, pady=10)
        ttk.Entry(form, textvariable=self.template_id, width=40).grid(
            row=2, column=1, sticky=tk.EW, pady=10, padx=(12, 0))

        ttk.Label(
            form,
            text="Template ID identifies which credential template to provision",
            font=('Arial', 8), foreground='gray',
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(0, 4))

        btns = ttk.Frame(main)
        btns.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(btns, text="Test Connection", command=self._test).pack(side=tk.LEFT)
        ttk.Button(btns, text="Cancel", command=self.dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="OK", command=self._ok).pack(side=tk.RIGHT, padx=(0, 8))

    def _validate(self) -> bool:
        for val, name in [
            (self.account_id.get(),  "Account ID"),
            (self.api_secret.get(),  "API Secret"),
            (self.template_id.get(), "Template ID"),
        ]:
            if not val.strip():
                messagebox.showerror("Validation Error", f"{name} is required")
                return False
        return True

    def _test(self):
        if not self._validate():
            return
        if not check_internet_connectivity():
            messagebox.showerror("No Internet", "No internet connection detected")
            return
        try:
            ag = AccessGrid(self.account_id.get().strip(), self.api_secret.get().strip())
            cards = ag.access_cards.list(template_id=self.template_id.get().strip())
            messagebox.showinfo(
                "Success",
                f"AccessGrid connection successful!\nFound {len(cards)} existing card(s)."
            )
        except AccessGridError as e:
            messagebox.showerror("API Error", f"AccessGrid API error:\n{e}")
        except Exception as e:
            messagebox.showerror("Connection Failed", f"AccessGrid connection failed:\n{e}")

    def _ok(self):
        if not self._validate():
            return
        self.result = {
            'account_id':  self.account_id.get().strip(),
            'api_secret':  self.api_secret.get().strip(),
            'template_id': self.template_id.get().strip(),
        }
        self.dialog.destroy()
