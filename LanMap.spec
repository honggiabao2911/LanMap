# -*- mode: python ; coding: utf-8 -*-
from importlib.util import find_spec
from PyInstaller.utils.hooks import collect_data_files

datas = [('LanMap1.png', '.'), ('LanMap-Storm.ico', '.')]
datas += collect_data_files('customtkinter')


a = Analysis(
    ['lanmap.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['PIL._tkinter_finder'] if find_spec('PIL._tkinter_finder') else [],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
splash = Splash(
    'LanMap-Boot.png',
    binaries=a.binaries,
    datas=a.datas,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.datas,
    [],
    name='LanMap',
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
    icon=['LanMap-Storm.ico'],
)
