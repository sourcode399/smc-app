"""
watcher.py — WORKER THEO DÕI & CẢNH BÁO (chạy nền)
====================================================
Chạy độc lập với app Streamlit. Cứ mỗi `INTERVAL` giây:
  1) đọc danh sách mã theo dõi từ database (smc_watch.db)
  2) lấy giá + tính kế hoạch (entry) cho từng mã
  3) nếu giá GẦN vùng vào (trong near_pct %) -> gửi cảnh báo Telegram
  4) ghi log để không gửi trùng

CÁCH CHẠY (máy phải bật, KHÔNG cần mở app Streamlit):
    # đặt biến môi trường Telegram trước (Windows):
    set TELEGRAM_TOKEN=123456:ABC...
    set TELEGRAM_CHAT_ID=987654321
    python watcher.py

Dừng: Ctrl + C.

LƯU Ý: đây là worker LOCAL (máy bật mới chạy). Sau này muốn chạy 24/7 kể cả khi
tắt máy thì mang đúng file này lên cloud (Render/Railway...).
"""

from __future__ import annotations
import os
import time
import datetime as dt

from smc.data import get_candles
from smc.decision import decide
from smc import watchlist as wl
from smc.notify import send_telegram

INTERVAL = int(os.environ.get("WATCH_INTERVAL", "120"))   # giây giữa 2 vòng quét


def _fmt(p: float) -> str:
    a = abs(p)
    if a >= 1000: return f"{p:,.2f}"
    if a >= 1:    return f"{p:.2f}"
    if a >= 0.01: return f"{p:.4f}"
    return f"{p:.8f}".rstrip("0")


def check_one(w: wl.WatchItem) -> str | None:
    """Kiểm tra 1 mã. Trả về nội dung cảnh báo nếu giá gần entry, ngược lại None."""
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
        dist_pct = abs(last - entry_mid) / entry_mid * 100

        if dist_pct <= w.near_pct:
            # chống gửi trùng
            if wl.already_alerted(w.id, p.direction, entry_mid):
                return None
            wl.log_alert(w.id, p.direction, entry_mid)
            return (f"🔔 <b>{w.name}</b> ({w.symbol}) — {w.timeframe}\n"
                    f"Giá <b>{_fmt(last)}</b> đang GẦN vùng vào ({dist_pct:.2f}%)\n"
                    f"Lệnh gợi ý: <b>{p.direction}</b>\n"
                    f"Vùng vào: {_fmt(p.entry_bottom)}–{_fmt(p.entry_top)}\n"
                    f"SL: {_fmt(p.stoploss)} | TP1: {_fmt(p.takeprofit)} | R:R {p.rr}\n"
                    f"⚠️ Chỉ là gợi ý — tự xem chart + quản lý vốn trước khi vào.")
        return None
    except Exception as e:
        print(f"  [lỗi {w.symbol}] {e}")
        return None


def run_once() -> int:
    """Quét 1 vòng tất cả mã đang bật. Trả số cảnh báo đã gửi."""
    items = wl.list_enabled()
    sent = 0
    for w in items:
        msg = check_one(w)
        if msg:
            ok = send_telegram(msg)
            print(f"  -> cảnh báo {w.symbol}: {'đã gửi' if ok else 'gửi lỗi'}")
            sent += ok
    return sent


def main():
    wl.init_db()
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("⚠️  Chưa đặt TELEGRAM_TOKEN / TELEGRAM_CHAT_ID. "
              "Đặt biến môi trường rồi chạy lại. (Xem hướng dẫn trong smc/notify.py)")
        return
    print(f"▶ Worker theo dõi đã chạy. Quét mỗi {INTERVAL}s. Ctrl+C để dừng.")
    send_telegram("✅ Worker theo dõi SMC đã khởi động — sẽ báo khi có mã gần vùng vào.")
    while True:
        ts = dt.datetime.now().strftime("%H:%M:%S")
        items = wl.list_enabled()
        print(f"[{ts}] quét {len(items)} mã…")
        try:
            n = run_once()
            if n:
                print(f"   gửi {n} cảnh báo.")
        except Exception as e:
            print("Lỗi vòng quét:", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
