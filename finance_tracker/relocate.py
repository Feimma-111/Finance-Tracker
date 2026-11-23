"""One-time move of the database out of the project folder.

Older versions kept the database at <project>/data/finance.db. That folder is
inside the project (so deleting it, re-cloning, or `git clean -xdf` would take
the data with it) and, on this Mac, inside iCloud-synced Documents (syncing a
database while it's in use can corrupt it). The first time a newer version
starts, the data is moved to the default location -- carefully:

1. A consistent copy is made with SQLite's backup API and integrity-checked.
2. Every table's row count is compared between old and new; any mismatch stops
   the move and leaves everything where it was.
3. Existing backups are copied along.
4. The old file is renamed (not deleted) so nothing keeps using it by mistake,
   and a note next to it says where the data went.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Dict, Optional, Union

from . import backup


class RelocationError(Exception):
    pass


def _row_counts(path: Path) -> Dict[str, int]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        conn.close()


def prepare(db_path: str) -> str:
    """Run at startup. If using the default location, move old data there first.

    Returns the database path to actually use -- if the move fails for any
    reason, the old location keeps working rather than showing an empty app.
    """
    from .paths import PROJECT_DB, using_default_location

    if not using_default_location(db_path):
        return db_path
    try:
        note = move_database(PROJECT_DB, db_path)
    except (RelocationError, backup.BackupError, OSError, sqlite3.Error) as exc:
        print(f"Couldn't move your data to {db_path}: {exc}\nStill using {PROJECT_DB} for now.")
        return str(PROJECT_DB)
    if note:
        print(note)
    return db_path


def move_database(old: Union[str, Path], new: Union[str, Path]) -> Optional[str]:
    """Move ``old`` to ``new`` if ``new`` doesn't exist yet. Returns a message, or None."""
    old, new = Path(old), Path(new)
    if new.exists() or not old.exists():
        return None

    new.parent.mkdir(parents=True, exist_ok=True)
    backup.secure(new.parent, 0o700)
    staging = new.with_name(new.name + ".moving")
    try:
        backup.copy_database(old, staging)  # consistent copy + integrity check
        before, after = _row_counts(old), _row_counts(staging)
        if before != after:
            raise RelocationError(f"the copy didn't match the original ({before} vs {after})")
        backup.secure(staging, 0o600)
        os.replace(staging, new)
    finally:
        if staging.exists():
            staging.unlink()

    # Bring the existing backups along.
    old_backups, new_backups = old.parent / "backups", new.parent / "backups"
    if old_backups.is_dir():
        new_backups.mkdir(exist_ok=True)
        backup.secure(new_backups, 0o700)
        for item in old_backups.iterdir():
            if item.is_file() and not (new_backups / item.name).exists():
                shutil.copy2(item, new_backups / item.name)
                backup.secure(new_backups / item.name, 0o600)

    # Keep the old copy until you've checked everything, but out of the way.
    retired = old.with_name(old.name + ".moved")
    os.replace(old, retired)
    (old.parent / "MOVED.txt").write_text(
        "Your finance data moved to:\n"
        f"  {new}\n\n"
        f"{retired.name} (and backups/) here are the old copies, kept just in case.\n"
        "Once you've checked the app shows everything, you can delete this whole data/ folder.\n"
    )
    return (
        f"Moved your data to {new}\n"
        f"  (the old copy is at {retired}; delete the project's data/ folder once you've checked everything)"
    )
