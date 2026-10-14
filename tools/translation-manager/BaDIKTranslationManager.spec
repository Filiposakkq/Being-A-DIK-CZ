# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for BaDIKTranslationManager.exe (one file, no console window).
# Build with build_exe.bat (or: py -m PyInstaller --noconfirm --clean BaDIKTranslationManager.spec).
# The UI files (prehled/ui) are bundled; settings live in %APPDATA%\BaDIKTranslationManager, project data in
# <translation folder>\_progress_data, so the exe does not depend on the folder it is started from.
import os

here = os.path.dirname(os.path.abspath(SPEC))

datas = [(os.path.join(here, "prehled", "ui"), os.path.join("prehled", "ui"))]
binaries, hiddenimports = [], []
try:                                   # pywebview is optional; without it the browser fallback is used
    from PyInstaller.utils.hooks import collect_all
    d, b, h = collect_all("webview")
    datas += d
    binaries += b
    hiddenimports += h
except Exception as exc:               # noqa: BLE001
    print("pywebview not bundled:", exc)

a = Analysis(
    [os.path.join(here, "progress.py")],
    pathex=[here],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "unittest.mock"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BaDIKTranslationManager",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
