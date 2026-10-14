from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def ensure_parent_dir(db_path: str) -> None:
    parent = Path(db_path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connect(db_path: str) -> Iterator[sqlite3.Connection]:
    ensure_parent_dir(db_path)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def db_path_from_env(env_name: str, default_path: str) -> str:
    return os.getenv(env_name, default_path)
