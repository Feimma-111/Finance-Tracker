"""Where the app keeps its files. Shared by the terminal app and the web API.

Your data lives in the operating system's per-user application-data folder,
outside the project, so that:
  * deleting or re-cloning the project (or `git clean -xdf`) can't touch it, and
  * it isn't inside a folder that iCloud (or similar) syncs while it's in use.

    macOS     ~/Library/Application Support/Finance Tracker/finance.db
    Linux     ~/.local/share/finance-tracker/finance.db   (e.g. a Raspberry Pi)
    Windows   %APPDATA%\\Finance Tracker\\finance.db

Set $FINANCE_TRACKER_DB (or pass --db) to use a different file.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
LEGACY_FILE = PROJECT_ROOT / "information_save_file"   # the very first version's save file
PROJECT_DB = PROJECT_ROOT / "data" / "finance.db"        # where data lived before it moved


def default_data_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Finance Tracker"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming") / "Finance Tracker"
    return Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "finance-tracker"


DEFAULT_DB = default_data_dir() / "finance.db"
# CSV exports from the terminal app go somewhere easy to find (and not synced).
EXPORT_DIR = Path.home() / "Downloads" if (Path.home() / "Downloads").is_dir() else default_data_dir() / "exports"


def database_path() -> str:
    """The database to use: $FINANCE_TRACKER_DB if set, else the default location."""
    return os.environ.get("FINANCE_TRACKER_DB", str(DEFAULT_DB))


def using_default_location(db_path: str) -> bool:
    return "FINANCE_TRACKER_DB" not in os.environ and Path(db_path) == DEFAULT_DB
