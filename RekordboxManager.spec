# Build with: .venv\Scripts\python.exe -m PyInstaller RekordboxManager.spec
from PyInstaller.utils.hooks import collect_data_files, copy_metadata
from rekordbox_manager import __version__

license_metadata = []
for package in ("pyrekordbox", "PySide6-Essentials", "PySide6-Addons", "shiboken6", "sqlcipher3-wheels", "Send2Trash",
                "pywin32", "SQLAlchemy", "numpy", "psutil", "construct", "bidict", "python-dateutil"):
    license_metadata += copy_metadata(package)

analysis = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=collect_data_files("pyrekordbox") + license_metadata + [("README.md", "."), ("THIRD_PARTY_NOTICES.md", ".")],
    hiddenimports=["win32com.shell.shell", "win32com.shell.shellcon", "pythoncom", "pywintypes"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "tkinter", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
exe = EXE(
    archive, analysis.scripts, [], exclude_binaries=True,
    name="RekordboxDatabaseManager", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
collection = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False,
                     name=f"RekordboxDatabaseManager-{__version__}")
