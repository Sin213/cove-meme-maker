# PyInstaller spec for Cove Meme Maker (macOS .app bundle)
# Run via: pyinstaller packaging/cove-meme-maker-macos.spec
import os
from pathlib import Path

block_cipher = None
PROJECT_ROOT = Path(SPECPATH).parent
SRC = PROJECT_ROOT / "src"
ASSETS = SRC / "cove_meme_maker" / "assets"
TEMPLATES = SRC / "cove_meme_maker" / "templates"

_VERSION = os.environ.get("VERSION", "0.0.0")
_ICON = os.environ.get("ICON_ICNS_PATH", str(ASSETS / "cove_icon.png"))

a = Analysis(
    [str(PROJECT_ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[
        (str(ASSETS / "cove_icon.png"), "cove_meme_maker/assets"),
        (str(ASSETS / "fonts"), "cove_meme_maker/assets/fonts"),
        (str(TEMPLATES), "cove_meme_maker/templates"),
    ],
    hiddenimports=["cove_meme_maker.tab_web"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtPdf",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "tkinter",
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
    [],
    exclude_binaries=True,
    name="cove-meme-maker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=_ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="cove-meme-maker",
)

app = BUNDLE(
    coll,
    name="Cove Meme Maker.app",
    icon=_ICON,
    bundle_identifier="com.cove.meme-maker",
    info_plist={
        "CFBundleName": "Cove Meme Maker",
        "CFBundleDisplayName": "Cove Meme Maker",
        "CFBundleShortVersionString": _VERSION,
        "CFBundleVersion": _VERSION,
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        "LSMinimumSystemVersion": "12.0",
    },
)
