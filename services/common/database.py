"""PostgreSQL connections, bounded pools and transaction helpers."""
from __future__ import annotations

import atexit
from contextlib import contextmanager
import os
from threading import Lock
from typing import Iterator

from psycopg import Connection, IntegrityError
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_pools: dict[str, ConnectionPool] = {}
_guard = Lock()


def database_url_from_env(name: str) -> str:
    return os.getenv(name, '')


def pool_for(database_url: str) -> ConnectionPool:
    if not database_url.startswith(('postgresql://', 'postgres://')):
        raise ValueError('Configure IDENTITY_DATABASE_URL, CUSTOMERS_DATABASE_URL and WORKSHOP_DATABASE_URL with PostgreSQL URLs. SQLite files are not supported.')
    with _guard:
        pool = _pools.get(database_url)
        if pool is None:
            pool = ConnectionPool(
                database_url, min_size=0, max_size=int(os.getenv('DB_POOL_MAX_SIZE', '10')),
                timeout=10, kwargs={'row_factory':dict_row, 'connect_timeout':5},
                check=ConnectionPool.check_connection, open=False,
            )
            pool.open()
            _pools[database_url] = pool
        return pool


@contextmanager
def connect(database_url: str) -> Iterator[Connection]:
    with pool_for(database_url).connection() as connection:
        with connection.transaction():
            yield connection


def close_pool(database_url: str) -> None:
    with _guard:
        pool = _pools.pop(database_url, None)
    if pool:
        pool.close()


def close_pools() -> None:
    for database_url in list(_pools):
        close_pool(database_url)


def table_columns(db: Connection, table: str) -> set[str]:
    return {row['name'] for row in db.execute(
        'SELECT column_name AS name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=%s', (table,)
    )}


def write_lock(db: Connection, scope: str = 'web-writes') -> None:
    # Serialize read/validate/write sequences inside this service/schema until commit.
    db.execute('SELECT pg_advisory_xact_lock(hashtext(current_schema()), hashtext(%s))', (scope,))


atexit.register(close_pools)
