"""Automatic backups of the database.

* Copies are made with SQLite's online backup API, so each one is consistent
  even if the app is writing at that moment (a plain file copy might not be).
* Every new copy is checked with ``PRAGMA integrity_check`` before it's kept.
* Daily backups are named ``finance-YYYY-MM-DD.db`` (the newest 30 are kept);
  safety copies made before an import, a restore, or a schema upgrade carry a
  label and a time (the newest 10 of those are kept).
* Backups live in a ``backups`` folder next to the database. Files are made
  readable only by your user account.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

KEEP_DAILY = 30
KEEP_LABELED = 10
_DAILY = re.compile(r"^finance-\d{4}-\d{2}-\d{2}\.db$")
_LABELED = re.compile(r"^finance-\d{4}-\d{2}-\d{2}-\d{6}-[a-z0-9-]+\.db$")


class BackupError(Exception):
    pass


def backup_dir(db_path: Union[str, Path]) -> Path:
    return Path(db_path).resolve().parent / "backups"


def secure(path: Union[str, Path], mode: int) -> None:
    """Restrict permissions (e.g. 0o600 for files) -- best effort."""
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def secure_database(db_path: Union[str, Path]) -> None:
    """Make the database (and its folder) private to your user account."""
    path = Path(db_path)
    if path.exists():
        secure(path, 0o600)
        secure(path.parent, 0o700)


def copy_database(source: Union[str, Path], target: Union[str, Path]) -> None:
    """Consistent copy of one SQLite file into another, then an integrity check."""
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    check = sqlite3.connect(str(target))
    try:
        result = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if result != "ok":
        raise BackupError(f"the copy failed its integrity check: {result}")


def make_backup(db_path: Union[str, Path], *, label: Optional[str] = None,
                now: Optional[datetime] = None) -> Optional[Path]:
    """Back up the database. Without a label, at most once per day.

    Returns the new file, or None if there was nothing to do (no database
    yet, or today's daily backup already exists).
    """
    if str(db_path) == ":memory:" or not Path(db_path).exists():
        return None
    now = now or datetime.now()
    folder = backup_dir(db_path)
    folder.mkdir(parents=True, exist_ok=True)
    secure(folder, 0o700)
    if label:
        name = f"finance-{now:%Y-%m-%d-%H%M%S}-{re.sub(r'[^a-z0-9]+', '-', label.lower()).strip('-')}.db"
    else:
        name = f"finance-{now:%Y-%m-%d}.db"
    target = folder / name
    if target.exists() and not label:
        return None  # already backed up today
    temporary = target.with_name(target.name + ".tmp")
    try:
        copy_database(db_path, temporary)
        secure(temporary, 0o600)
        os.replace(temporary, target)  # appears all at once, never half-written
    finally:
        if temporary.exists():
            temporary.unlink()
    prune(folder)
    return target


def prune(folder: Path) -> None:
    for pattern, keep in ((_DAILY, KEEP_DAILY), (_LABELED, KEEP_LABELED)):
        files = sorted((p for p in folder.iterdir() if pattern.match(p.name)), key=lambda p: p.name, reverse=True)
        for old in files[keep:]:
            old.unlink()


def list_backups(db_path: Union[str, Path]) -> List[Dict[str, object]]:
    folder = backup_dir(db_path)
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if _DAILY.match(p.name) or _LABELED.match(p.name)]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {"name": p.name, "size": p.stat().st_size,
         "created": datetime.fromtimestamp(p.stat().st_mtime).astimezone().isoformat(timespec="seconds")}
        for p in files
    ]


def restore(db_path: Union[str, Path], backup_file: Union[str, Path]) -> Path:
    """Replace the database with a backup. The current database is backed up first."""
    backup_file = Path(backup_file)
    if not backup_file.is_file():
        raise BackupError(f"no backup at {backup_file}")
    check = sqlite3.connect(f"file:{backup_file}?mode=ro", uri=True)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("that backup is damaged; pick another one")
    finally:
        check.close()
    safety = make_backup(db_path, label="before-restore")
    copy_database(backup_file, db_path)
    secure_database(db_path)
    return safety or Path(db_path)
