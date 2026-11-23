"""Where the app keeps its files. Shared by the terminal app and the web API."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "finance.db"
LEGACY_FILE = PROJECT_ROOT / "information_save_file"
EXPORT_DIR = PROJECT_ROOT / "exports"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def database_path() -> str:
    """The database to use: $FINANCE_TRACKER_DB if set, else data/finance.db."""
    return os.environ.get("FINANCE_TRACKER_DB", str(DEFAULT_DB))
