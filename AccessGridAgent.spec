# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — builds on macOS, Linux, and Windows.

import os
import sys

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('assets/logo.png', 'assets'),
    ],
    hiddenimports=[
        'accessgrid',
        'requests',
        'urllib3',
        'cryptography',
        'PIL',
        'sentry_sdk',
        'sentry_sdk.integrations.logging',
        'sqlite3',
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/hook-cryptography.py'] if os.path.exists('hooks/hook-cryptography.py') else [],
    excludes=[
        'pyodbc',
        'cx_Oracle',
        'oracledb',
        'matplotlib',
        'numpy',
        'pandas',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AccessGridAvigilonAgent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/logo.png',
)

# macOS: wrap the single-file binary in a proper .app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='AccessGridAvigilonAgent.app',
        icon='assets/logo.png',
        bundle_identifier='com.accessgrid.avigilon-agent',
        info_plist={
            'NSHighResolutionCapable': True,
            'NSPrincipalClass': 'NSApplication',
            'CFBundleShortVersionString': '1.0.0',
        },
    )
