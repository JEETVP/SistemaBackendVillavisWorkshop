"""SQLite support only for historical data import, never for live API services."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import re


@contextmanager
def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize(directory):
    schemas = Path(__file__).resolve().parents[2] / "scripts" / "legacy_schema"
    for name in ("identity", "customers", "workshop"):
        with connect(Path(directory) / f"{name}.db") as db:
            source = (schemas / f"{name}.sql").read_text(encoding="utf-8")
            source = re.sub(r'CREATE TABLE (?!IF NOT EXISTS)', 'CREATE TABLE IF NOT EXISTS ', source)
            source = re.sub(r'CREATE (UNIQUE )?INDEX (?!IF NOT EXISTS)',
                            lambda match: 'CREATE ' + (match[1] or '') + 'INDEX IF NOT EXISTS ', source)
            db.executescript(source)
