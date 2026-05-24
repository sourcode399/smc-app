"""
smc/watchlist.py — DANH SÁCH MÃ THEO DÕI CẢNH BÁO (SQLite)
============================================================
Lưu các mã bạn muốn được cảnh báo khi giá GẦN vùng vào lệnh (entry).
Dùng SQLite — chỉ là 1 file (smc_watch.db), không cần cài server.

Bảng watchlist:
    id, name, market, symbol, timeframe, htf_rule, near_pct, enabled
        near_pct : báo khi giá cách entry dưới ngưỡng này (%) — vd 0.5

Bảng alerts_log: lưu cảnh báo đã gửi để tránh spam trùng.
"""

from __future__ import annotations
import sqlite3
import os
from dataclasses import dataclass

# file DB nằm cùng thư mục dự án (worker và app dùng chung)
DB_PATH = os.environ.get("SMC_DB", os.path.join(os.path.dirname(__file__), "..", "smc_watch.db"))


@dataclass
class WatchItem:
    id: int
    name: str
    market: str
    symbol: str
    timeframe: str
    htf_rule: str
    near_pct: float
    enabled: int


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, market TEXT, symbol TEXT,
            timeframe TEXT DEFAULT '1h', htf_rule TEXT DEFAULT '4h',
            near_pct REAL DEFAULT 0.5, enabled INTEGER DEFAULT 1,
            UNIQUE(market, symbol, timeframe))""")
        c.execute("""CREATE TABLE IF NOT EXISTS alerts_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            watch_id INTEGER, direction TEXT, entry REAL,
            sent_at TEXT)""")


def add(name, market, symbol, timeframe="1h", htf_rule="4h", near_pct=0.5):
    init_db()
    with _conn() as c:
        c.execute("""INSERT OR REPLACE INTO watchlist
                     (name, market, symbol, timeframe, htf_rule, near_pct, enabled)
                     VALUES (?,?,?,?,?,?,1)""",
                  (name, market, symbol, timeframe, htf_rule, near_pct))


def remove(watch_id: int):
    with _conn() as c:
        c.execute("DELETE FROM watchlist WHERE id=?", (watch_id,))


def set_enabled(watch_id: int, enabled: bool):
    with _conn() as c:
        c.execute("UPDATE watchlist SET enabled=? WHERE id=?", (1 if enabled else 0, watch_id))


def list_all() -> list[WatchItem]:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT * FROM watchlist ORDER BY name").fetchall()
    return [WatchItem(**dict(r)) for r in rows]


def list_enabled() -> list[WatchItem]:
    return [w for w in list_all() if w.enabled]


# --- chống gửi trùng: chỉ gửi lại nếu entry đổi đáng kể hoặc đã qua lâu ---
def already_alerted(watch_id: int, direction: str, entry: float, tol: float = 0.002) -> bool:
    """Đã gửi cảnh báo gần giống (cùng hướng, entry sát nhau) gần đây chưa."""
    with _conn() as c:
        rows = c.execute("""SELECT direction, entry FROM alerts_log
                            WHERE watch_id=? ORDER BY id DESC LIMIT 5""", (watch_id,)).fetchall()
    for r in rows:
        if r["direction"] == direction and entry > 0 \
                and abs(r["entry"] - entry) / entry <= tol:
            return True
    return False


def log_alert(watch_id: int, direction: str, entry: float):
    import datetime as dt
    with _conn() as c:
        c.execute("""INSERT INTO alerts_log (watch_id, direction, entry, sent_at)
                     VALUES (?,?,?,?)""",
                  (watch_id, direction, entry, dt.datetime.now().isoformat(timespec="seconds")))


if __name__ == "__main__":
    init_db()
    add("Bitcoin", "crypto", "BTC/USDT", "1h", "4h", 0.5)
    add("Vàng", "commodity", "GC=F", "1h", "4h", 0.5)
    for w in list_all():
        print(w)
    print("DB:", os.path.abspath(DB_PATH))
