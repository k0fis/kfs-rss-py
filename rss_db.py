import psycopg2
import psycopg2.extras
from contextlib import contextmanager
import rss_config as cfg

_pool = None


def _get_conn():
    global _pool
    if _pool is None or _pool.closed:
        _pool = psycopg2.connect(
            dbname=cfg.DB_NAME, user=cfg.DB_USER, password=cfg.DB_PASSWORD,
            host=cfg.DB_HOST, port=cfg.DB_PORT
        )
        _pool.autocommit = False
    return _pool


@contextmanager
def transaction():
    conn = _get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def query(sql, params=None):
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception:
        conn.rollback()
        raise


def query_one(sql, params=None):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=None):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur.rowcount
    except Exception:
        conn.rollback()
        raise


def execute_returning(sql, params=None):
    conn = _get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            conn.commit()
            return cur.fetchone()
    except Exception:
        conn.rollback()
        raise
