"""
smc/notify.py — GỬI THÔNG BÁO TELEGRAM
=======================================
Gửi cảnh báo về điện thoại qua Telegram bot.

CÁCH LẤY TOKEN + CHAT ID (làm 1 lần):
1. Mở Telegram, tìm @BotFather -> /newbot -> đặt tên -> nhận TOKEN (dạng 123456:ABC...).
2. Nhắn 1 tin bất kỳ cho bot vừa tạo (để nó có quyền nhắn lại bạn).
3. Lấy CHAT ID: mở trình duyệt vào
   https://api.telegram.org/bot<TOKEN>/getUpdates
   tìm "chat":{"id": SỐ_NÀY ...} -> đó là CHAT ID của bạn.
4. Đặt 2 biến môi trường (hoặc nhập trong app/worker):
   TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
"""

from __future__ import annotations
import os
import urllib.request
import urllib.parse
import urllib.error


def send_telegram(text: str, token: str | None = None, chat_id: str | None = None) -> bool:
    """Gửi 1 tin nhắn Telegram. Trả True nếu gửi thành công."""
    token = token or os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise ValueError("Thiếu TELEGRAM_TOKEN hoặc TELEGRAM_CHAT_ID.")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text, "parse_mode": "HTML"
    }).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=15) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        # đọc lý do cụ thể mà Telegram trả về (rất hữu ích để gỡ lỗi)
        try:
            body = e.read().decode()
        except Exception:
            body = ""
        print(f"Lỗi gửi Telegram: HTTP {e.code} — {body}")
        return False
    except Exception as e:
        print("Lỗi gửi Telegram:", e)
        return False


if __name__ == "__main__":
    # python -m smc.notify  (cần đặt sẵn biến môi trường)
    ok = send_telegram("✅ Test cảnh báo từ SMC App — nếu bạn thấy tin này là đã chạy được!")
    print("Gửi:", "OK" if ok else "thất bại")
