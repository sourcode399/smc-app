"""
smc/data.py — TẦNG DỮ LIỆU (Phần 1)
====================================
Nhiệm vụ duy nhất của module này: lấy nến từ nhiều nguồn khác nhau và TRẢ VỀ
MỘT ĐỊNH DẠNG CHUNG để các phần sau (engine, backtest, UI) không cần quan tâm
dữ liệu đến từ đâu.

Định dạng chuẩn -> pandas.DataFrame với:
    index : DatetimeIndex (UTC)
    cột   : open, high, low, close, volume   (đều là float)

Nguồn hỗ trợ:
    - crypto  : qua ccxt   (Binance, Bybit, OKX, ...)   -> pip install ccxt
    - stock   : qua yfinance (cổ phiếu Mỹ, ETF, ...)     -> pip install yfinance
    - forex   : qua yfinance (cặp tiền dạng 'EURUSD=X')  hoặc broker API riêng

Triết lý: tách biệt "lấy dữ liệu" khỏi "phân tích". Mọi phần sau chỉ làm việc
với DataFrame chuẩn, nên sau này muốn đổi sàn / thêm nguồn chỉ sửa đúng file này.
"""

from __future__ import annotations
import time
import pandas as pd

# Các cột chuẩn mà toàn bộ app sẽ dùng
OHLCV = ["open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------------------
# Hàm chuẩn hoá dùng chung — mọi nguồn đều đi qua đây
# ---------------------------------------------------------------------------
def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Đưa DataFrame bất kỳ về đúng schema chuẩn: index thời gian UTC + 5 cột float."""
    df = df.copy()

    # đảm bảo có đủ 5 cột, ép kiểu số
    for col in OHLCV:
        if col not in df.columns:
            raise ValueError(f"Thiếu cột '{col}' trong dữ liệu nguồn")
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df[OHLCV]                       # chỉ giữ cột cần
    df = df[~df.index.duplicated(keep="last")]  # bỏ nến trùng timestamp
    df = df.sort_index()                 # thời gian tăng dần
    df = df.dropna()                     # bỏ nến lỗi
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "time"
    return df


# ---------------------------------------------------------------------------
# 1) CRYPTO — qua ccxt
# ---------------------------------------------------------------------------
def fetch_crypto(symbol: str = "BTC/USDT",
                 timeframe: str = "1h",
                 limit: int = 1000,
                 exchange: str = "binance") -> pd.DataFrame:
    """
    Lấy nến crypto qua ccxt.

    symbol    : ví dụ 'BTC/USDT', 'ETH/USDT'
    timeframe : '1m','5m','15m','1h','4h','1d', ...
    limit     : số nến (nhiều sàn giới hạn ~1000/lần)
    exchange  : 'binance', 'bybit', 'okx', ...

    Trả về DataFrame chuẩn.
    """
    import ccxt  # import trong hàm để ai không dùng crypto khỏi cần cài

    ex = getattr(ccxt, exchange)({"enableRateLimit": True})
    raw = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    # ccxt trả: [[ms_timestamp, open, high, low, close, volume], ...]
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return _normalize(df)


def fetch_crypto_history(symbol: str = "BTC/USDT",
                         timeframe: str = "1h",
                         since_days: int = 365,
                         exchange: str = "binance") -> pd.DataFrame:
    """
    Lấy LỊCH SỬ dài (cho backtest) bằng cách phân trang nhiều lần.
    since_days : lấy ngược về bao nhiêu ngày.
    """
    import ccxt
    ex = getattr(ccxt, exchange)({"enableRateLimit": True})
    ms_per_candle = ex.parse_timeframe(timeframe) * 1000
    since = ex.milliseconds() - since_days * 24 * 60 * 60 * 1000
    all_rows = []
    while True:
        batch = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if not batch:
            break
        all_rows += batch
        since = batch[-1][0] + ms_per_candle
        if len(batch) < 1000:           # hết dữ liệu
            break
        time.sleep(ex.rateLimit / 1000)  # tôn trọng rate limit
    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return _normalize(df)


# ---------------------------------------------------------------------------
# 2) STOCK / FOREX — qua yfinance
# ---------------------------------------------------------------------------
def fetch_yahoo(symbol: str,
                interval: str = "1h",
                period: str = "60d") -> pd.DataFrame:
    """
    Lấy nến cổ phiếu / forex qua yfinance.

    symbol   : 'AAPL', 'SPY' (cổ phiếu) | 'EURUSD=X', 'JPY=X' (forex) | 'BTC-USD' (crypto qua yahoo)
    interval : '1m','5m','15m','30m','60m','1h','1d','1wk'
    period   : '7d','60d','1y','max' (yahoo giới hạn: nến phút chỉ vài chục ngày gần nhất)
    """
    import yfinance as yf

    df = yf.download(symbol, interval=interval, period=period,
                     auto_adjust=False, progress=False)
    if df.empty:
        raise ValueError(f"Không lấy được dữ liệu cho '{symbol}' "
                         f"(kiểm tra mã / interval / period)")
    # yfinance có thể trả cột MultiIndex khi tải 1 mã -> làm phẳng
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                            "Close": "close", "Volume": "volume"})
    return _normalize(df)


# ---------------------------------------------------------------------------
# Bộ điều phối thống nhất — phần sau chỉ cần gọi get_candles(...)
# ---------------------------------------------------------------------------
def get_candles(market: str, symbol: str, timeframe: str, **kw) -> pd.DataFrame:
    """
    Cổng vào duy nhất cho cả app.

    market : 'crypto'  -> qua ccxt
             mọi giá trị khác ('forex','commodity','stock','index') -> qua Yahoo
    Ví dụ:
        get_candles('crypto',    'BTC/USDT', '4h')
        get_candles('commodity', 'GC=F',     '1h')   # vàng
        get_candles('commodity', 'CL=F',     '1h')   # dầu WTI
        get_candles('forex',     'EURUSD=X', '1h')
        get_candles('index',     '^GSPC',    '1d')   # S&P 500
    """
    market = market.lower()
    if market == "crypto":
        return fetch_crypto(symbol, timeframe, **kw)
    if market == "vn":                       # chứng khoán Việt Nam qua vnstock
        from smc.data_vn import fetch_vn
        return fetch_vn(symbol, interval=timeframe, **kw)
    # forex / commodity / stock / index đều dùng Yahoo
    return fetch_yahoo(symbol, interval=timeframe, **kw)


# ---------------------------------------------------------------------------
# DỮ LIỆU GIẢ — để test/demo khi chưa có mạng hoặc chưa cài lib
# ---------------------------------------------------------------------------
def make_synthetic(n: int = 300, seed: int = 7, start_price: float = 100.0) -> pd.DataFrame:
    """Sinh nến mô phỏng (trend + sideway xen kẽ) cùng schema chuẩn để test engine."""
    import numpy as np
    rng = np.random.default_rng(seed)
    prices, price = [], start_price
    drift = 0.0
    rows = []
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    seg_left = 0
    for _ in range(n):
        if seg_left <= 0:                       # bắt đầu đoạn trend mới
            seg_left = rng.integers(15, 40)
            r = rng.random()
            drift = 0.5 if r < 0.4 else (-0.5 if r < 0.78 else 0.0)
        seg_left -= 1
        o = price
        move = drift * (0.8 + rng.random()) + (rng.random() - 0.5) * 2.2
        c = o + move
        wick = 0.4 + rng.random() * 1.4
        h = max(o, c) + rng.random() * wick
        l = min(o, c) - rng.random() * wick
        vol = 100 + rng.random() * 900
        rows.append((o, h, l, c, vol))
        price = c
    df = pd.DataFrame(rows, columns=OHLCV, index=idx)
    df.index.name = "time"
    return df


if __name__ == "__main__":
    # Chạy thử nhanh: python -m smc.data
    df = make_synthetic(20)
    print("Schema chuẩn — 5 dòng đầu:\n")
    print(df.head())
    print("\nKiểu dữ liệu:")
    print(df.dtypes)
    print(f"\nTổng cộng {len(df)} nến, từ {df.index[0]} đến {df.index[-1]}")
