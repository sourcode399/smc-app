"""
check_alerts.py — KIỂM TRA & CẢNH BÁO (chạy 1 lần, cho GitHub Actions)
=======================================================================
Khác watcher.py (chạy vòng lặp liên tục): file này chạy MỘT lần rồi thoát.
GitHub Actions sẽ gọi nó định kỳ (vd mỗi 15 phút) theo lịch trong workflow.

Đọc danh sách mã từ Supabase -> lấy giá -> gửi Telegram nếu giá gần entry.

Biến môi trường cần (đặt trong GitHub Secrets):
    DATABASE_URL        (chuỗi kết nối Supabase)
    TELEGRAM_TOKEN
    TELEGRAM_CHAT_ID
"""

from __future__ import annotations
import sys

from smc.data import get_candles
from smc.decision import decide
from smc import db
from smc.notify import send_telegram


def _fmt(p: float) -> str:
    a = abs(p)
    if a >= 1000: return f"{p:,.2f}"
    if a >= 1:    return f"{p:.2f}"
    if a >= 0.01: return f"{p:.4f}"
    return f"{p:.8f}".rstrip("0")


def check_one(w) -> str | None:
    try:
        df = get_candles(w.market, w.symbol, w.timeframe)
        if df is None or len(df) < 60:
            return None
        d = decide(df, htf_rule=w.htf_rule)
        if not d.plan:
            return None
        p = d.plan
        last = d.last_price
        entry_mid = (p.entry_top + p.entry_bottom) / 2
        dist = abs(last - entry_mid) / entry_mid * 100
        if dist > w.near_pct:
            return None
        if db.already_alerted(w.id, p.direction, entry_mid):
            return None
        db.log_alert(w.id, p.direction, entry_mid)
        return (f"🔔 <b>{w.name}</b> ({w.symbol}) — {w.timeframe}\n"
                f"Giá <b>{_fmt(last)}</b> đang GẦN vùng vào ({dist:.2f}%)\n"
                f"Lệnh gợi ý: <b>{p.direction}</b>\n"
                f"Vùng vào: {_fmt(p.entry_bottom)}–{_fmt(p.entry_top)}\n"
                f"SL: {_fmt(p.stoploss)} | TP1: {_fmt(p.takeprofit)} | R:R {p.rr}\n"
                f"⚠️ Chỉ là gợi ý — tự xem chart + quản lý vốn trước khi vào.")
    except Exception as e:
        print(f"  [lỗi {w.symbol}] {e}", file=sys.stderr)
        return None


def main():
    db.init_db()
    items = db.list_enabled()
    print(f"Quét {len(items)} mã…")
    sent = 0
    for w in items:
        msg = check_one(w)
        if msg:
            ok = send_telegram(msg)
            print(f"  -> {w.symbol}: {'đã gửi' if ok else 'gửi lỗi'}")
            sent += bool(ok)
    print(f"Xong. Đã gửi {sent} cảnh báo.")


if __name__ == "__main__":
    main()
