"""Uploaded-file storage.

STORAGE_BACKEND:
* ``fs`` (default): files under STORAGE_DIR, keyed by content hash.
* ``db``: bytes in the ``stored_blob`` table. For hosts whose disk is wiped on
  restart (e.g. Render's free tier), so uploads live as long as the database.

Rendered page images are a cache and always go to STORAGE_DIR; they are
rebuilt from the stored file when missing.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from .config import get_settings
from .models import StoredBlob


def _db_mode() -> bool:
    return get_settings().storage_backend == "db"


def put(db: Session, key: str, data: bytes) -> None:
    if _db_mode():
        if db.get(StoredBlob, key) is None:
            db.add(StoredBlob(key=key, data=data))
            db.flush()
        return
    path = Path(get_settings().storage_dir) / key
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def get(db: Session | None, key: str) -> bytes | None:
    if _db_mode():
        if db is None:
            return None
        blob = db.get(StoredBlob, key)
        return bytes(blob.data) if blob else None
    path = Path(get_settings().storage_dir) / key
    return path.read_bytes() if path.exists() else None


def cache_dir() -> Path:
    return Path(get_settings().storage_dir)
