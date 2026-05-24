"""
smc/db.py — KẾT NỐI DATABASE CLOUD (Supabase / Postgres)
=========================================================
Thay cho SQLite, để app (máy bạn) và GitHub Actions (cloud) DÙNG CHUNG dữ liệu.

Cần biến môi trường DATABASE_URL — chuỗi kết nối Postgres của Supabase, dạng:
    postgresql://postgres:[MẬT_KHẨU]@[HOST]:5432/postgres
(Lấy trong Supabase: Project Settings -> Database -> Connection string -> URI)

Cài thư viện:  pip install psycopg2-binary
"""

from __future__ import annotations
import os
from dataclasses import dataclass

DATABASE_URL = os.environ.get("DATABASE_URL", "")


@dataclass
class WatchItem:
    id: int
    name: str
    market: str
    symbol: str
    timeframe: str
    htf_rule: str
    near_pct: float
    enabled: bool


def _conn():
    import psycopg2
    if not DATABASE_URL:
        raise ValueError("Chưa đặt DATABASE_URL (chuỗi kết nối Supabase).")
    return psycopg2.connect(DATABASE_URL)


def init_db():
    with _conn() as c, c.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS watchlist (
            id SERIAL PRIMARY KEY,
            name TEXT, market TEXT, symbol TEXT,
            timeframe TEXT DEFAULT '1h', htf_rule TEXT DEFAULT '4h',
            near_pct REAL DEFAULT 0.5, enabled BOOLEAN DEFAULT TRUE,
            UNIQUE(market, symbol, timeframe))""")
        cur.execute("""CREATE TABLE IF NOT EXISTS alerts_log (
            id SERIAL PRIMARY KEY,
            watch_id INTEGER, direction TEXT, entry REAL,
            sent_at TIMESTAMP DEFAULT NOW())""")
        c.commit()


def add(name, market, symbol, timeframe="1h", htf_rule="4h", near_pct=0.5):
    init_db()
    with _conn() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO watchlist
            (name, market, symbol, timeframe, htf_rule, near_pct, enabled)
            VALUES (%s,%s,%s,%s,%s,%s,TRUE)
            ON CONFLICT (market, symbol, timeframe)
            DO UPDATE SET near_pct=EXCLUDED.near_pct, enabled=TRUE""",
            (name, market, symbol, timeframe, htf_rule, near_pct))
        c.commit()


def remove(watch_id: int):
    with _conn() as c, c.cursor() as cur:
        cur.execute("DELETE FROM watchlist WHERE id=%s", (watch_id,))
        c.commit()


def set_enabled(watch_id: int, enabled: bool):
    with _conn() as c, c.cursor() as cur:
        cur.execute("UPDATE watchlist SET enabled=%s WHERE id=%s", (enabled, watch_id))
        c.commit()


def list_all() -> list[WatchItem]:
    init_db()
    with _conn() as c, c.cursor() as cur:
        cur.execute("""SELECT id,name,market,symbol,timeframe,htf_rule,near_pct,enabled
                       FROM watchlist ORDER BY name""")
        rows = cur.fetchall()
    return [WatchItem(*r) for r in rows]


def list_enabled() -> list[WatchItem]:
    return [w for w in list_all() if w.enabled]


def already_alerted(watch_id: int, direction: str, entry: float, tol: float = 0.002) -> bool:
    """Đã gửi cảnh báo gần giống gần đây chưa (chống spam trùng)."""
    with _conn() as c, c.cursor() as cur:
        cur.execute("""SELECT direction, entry FROM alerts_log
                       WHERE watch_id=%s ORDER BY id DESC LIMIT 5""", (watch_id,))
        rows = cur.fetchall()
    for d, e in rows:
        if d == direction and entry > 0 and e and abs(e - entry) / entry <= tol:
            return True
    return False


def log_alert(watch_id: int, direction: str, entry: float):
    with _conn() as c, c.cursor() as cur:
        cur.execute("""INSERT INTO alerts_log (watch_id, direction, entry)
                       VALUES (%s,%s,%s)""", (watch_id, direction, entry))
        c.commit()


if __name__ == "__main__":
    # python -m smc.db  (cần đặt DATABASE_URL)
    init_db()
    print("Kết nối Supabase OK. Danh sách hiện tại:")
    for w in list_all():
        print(" ", w)
