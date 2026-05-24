"""
smc/data_vn.py — DỮ LIỆU CHỨNG KHOÁN VIỆT NAM (qua vnstock)
============================================================
Bổ sung nguồn dữ liệu thị trường VN (HOSE/HNX/UPCOM) cho app, vì Yahoo gần như
không hỗ trợ cổ phiếu Việt Nam.

Dùng thư viện vnstock (https://github.com/thinh-vu/vnstock):
    pip install -U vnstock

Trả về cùng SCHEMA CHUẨN như smc/data.py: DataFrame index thời gian (UTC) +
cột open/high/low/close/volume (float).

LƯU Ý:
- vnstock lấy dữ liệu từ công ty chứng khoán VN -> chính xác cho thị trường VN.
- Bản miễn phí có giới hạn lượt gọi API/phút (đăng nhập Google để tăng hạn mức).
- API có thể đổi giữa các phiên bản; module viết theo vnstock 3.x. Nếu lỗi, kiểm
  tra tài liệu phiên bản bạn cài.
"""

from __future__ import annotations
import datetime as _dt
import pandas as pd

# tái dùng hàm chuẩn hoá chung để mọi nguồn ra cùng một định dạng
from smc.data import _normalize, OHLCV


# map khung thời gian của app -> khung của vnstock
_TF_MAP = {"15m": "15m", "30m": "30m", "1h": "1H", "1H": "1H",
           "1d": "1D", "1D": "1D", "1w": "1W", "1W": "1W"}


def fetch_vn(symbol: str = "VCB",
             interval: str = "1D",
             start: str | None = None,
             end: str | None = None,
             source: str = "VCI") -> pd.DataFrame:
    """
    Lấy nến chứng khoán Việt Nam qua vnstock.

    symbol   : mã cổ phiếu ('VCB','FPT','HPG'...) hoặc chỉ số ('VNINDEX','VN30')
    interval : '15m','30m','1h','1d','1w'  (sẽ map sang định dạng vnstock)
    start/end: 'YYYY-MM-DD'. Bỏ trống -> mặc định lấy ~2 năm gần nhất (ngày),
               hoặc ~60 ngày gần nhất (intraday) cho hợp lý.
    source   : nguồn dữ liệu vnstock ('VCI','TCBS','MSN'...). 'VCI' thường ổn định.
    """
    try:
        from vnstock import Vnstock
    except ImportError as e:
        raise ImportError("Chưa cài vnstock. Chạy:  pip install -U vnstock") from e

    vn_interval = _TF_MAP.get(interval, "1D")
    intraday = vn_interval not in ("1D", "1W")

    # khoảng thời gian mặc định
    today = _dt.date.today()
    if end is None:
        end = today.isoformat()
    if start is None:
        back = 60 if intraday else 730        # intraday lấy ngắn, ngày lấy ~2 năm
        start = (today - _dt.timedelta(days=back)).isoformat()

    stock = Vnstock().stock(symbol=symbol, source=source)
    df = stock.quote.history(start=start, end=end, interval=vn_interval)
    if df is None or len(df) == 0:
        raise ValueError(f"Không lấy được dữ liệu cho '{symbol}' "
                         f"(kiểm tra mã / khung / nguồn).")

    # vnstock trả cột: time, open, high, low, close, volume (chữ thường)
    df = df.rename(columns={c: c.lower() for c in df.columns})
    if "time" in df.columns:
        df = df.set_index("time")
    elif "date" in df.columns:
        df = df.set_index("date")

    # đảm bảo đủ 5 cột rồi đưa qua chuẩn hoá chung
    for col in OHLCV:
        if col not in df.columns:
            raise ValueError(f"Dữ liệu vnstock thiếu cột '{col}' "
                             f"(API có thể đã đổi; kiểm tra phiên bản vnstock).")
    return _normalize(df)


if __name__ == "__main__":
    # Chạy thử (cần cài vnstock + có mạng): python -m smc.data_vn
    try:
        df = fetch_vn("VCB", "1D")
        print(df.tail())
        print(f"\nLấy được {len(df)} nến VCB.")
    except Exception as e:
        print("Lỗi:", e)
