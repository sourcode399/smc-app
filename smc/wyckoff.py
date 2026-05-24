"""
smc/wyckoff.py — WYCKOFF (Phần 6)
==================================
Wyckoff khó tự động hơn SMC vì dựa nhiều vào "đọc ý đồ" qua giá + volume + ngữ
cảnh. Ta KHÔNG cố ép máy phân loại phase A–E (quá chủ quan), mà chỉ bắt những
tín hiệu CODE ĐƯỢC ĐÁNG TIN:

    1) find_trading_range()  -> vùng đi ngang (ứng viên tích luỹ/phân phối)
    2) detect_springs()      -> SPRING: quét THỦNG đáy range rồi đóng cửa lại
                                trong range (phá đáy giả) -> tín hiệu TĂNG
    3) detect_upthrusts()    -> UPTHRUST: quét VƯỢT đỉnh range rồi đóng cửa lại
                                trong range (phá đỉnh giả) -> tín hiệu GIẢM
    4) analyze_wyckoff()     -> gộp lại + gợi ý thiên hướng

Ý tưởng cốt lõi của spring/upthrust: tay to "quét thanh khoản" — đẩy giá qua
biên để kích hoạt stoploss đám đông, gom hàng/xả hàng, rồi đảo chiều. Volume
cao tại cú quét càng xác nhận.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd


@dataclass
class TradingRange:
    start: int
    end: int
    top: float
    bottom: float
    @property
    def mid(self): return (self.top + self.bottom) / 2

@dataclass
class WyckoffSignal:
    idx: int
    kind: str               # 'spring' (tăng) / 'upthrust' (giảm)
    price: float            # mức quét (đáy với spring, đỉnh với upthrust)
    volume_spike: bool      # cú quét có volume cao bất thường không
    note: str
    confirmed: bool = False # đã có "test" volume thấp xác nhận chưa
    test_idx: int = -1      # vị trí nến test (nếu có)

@dataclass
class Climax:
    idx: int
    kind: str               # 'sc' = selling climax (bullish) / 'bc' = buying climax (bearish)
    price: float
    note: str

@dataclass
class WyckoffResult:
    trading_range: Optional[TradingRange]
    signals: list[WyckoffSignal]
    bias_hint: str          # 'accumulation' / 'distribution' / 'unclear'
    note: str
    climaxes: list = None    # danh sách Climax (SC/BC)
    absorption: list = None  # các nến hấp thụ (effort >> result)

    def __post_init__(self):
        if self.climaxes is None:
            self.climaxes = []
        if self.absorption is None:
            self.absorption = []


# ---------------------------------------------------------------------------
# 1) Trading range — vùng đi ngang
# ---------------------------------------------------------------------------
def find_trading_range(df: pd.DataFrame,
                       window: int = 40,
                       max_width_pct: float = 0.12,
                       min_touches: int = 3) -> Optional[TradingRange]:
    """
    Tìm vùng đi ngang trong `window` nến gần nhất.

    Wyckoff range thường RỘNG và DÀI hơn range của SMC, nên window & max_width
    để lớn hơn so với detect_range() ở Phần 4.
    Điều kiện: biên độ vừa phải + giá chạm cả biên trên lẫn biên dưới nhiều lần.
    """
    if len(df) < window:
        return None
    seg = df.iloc[-window:]
    # Dùng PHÂN VỊ thay vì min/max: đáy/đỉnh range là vùng giá "bình thường" hay
    # lui tới, KHÔNG phải spike cực trị. Nhờ vậy spring (thủng dưới q-low) và
    # upthrust (vượt trên q-high) nằm NGOÀI biên -> phát hiện được đúng.
    top = float(seg["high"].quantile(0.90))
    bottom = float(seg["low"].quantile(0.10))
    mid = (top + bottom) / 2
    if mid <= 0 or top <= bottom:
        return None
    if (top - bottom) / mid > max_width_pct:
        return None

    band = (top - bottom) * 0.15
    touch_top = int((seg["high"] >= top - band).sum())
    touch_bot = int((seg["low"] <= bottom + band).sum())
    if touch_top >= min_touches and touch_bot >= min_touches:
        return TradingRange(start=len(df) - window, end=len(df) - 1,
                            top=top, bottom=bottom)
    return None


# ---------------------------------------------------------------------------
# Tiện ích: volume có cao bất thường tại nến i không
# ---------------------------------------------------------------------------
def _volume_spike(df: pd.DataFrame, i: int, lookback: int = 20, mult: float = 1.5) -> bool:
    lo = max(0, i - lookback)
    avg = df["volume"].iloc[lo:i].mean()
    if pd.isna(avg) or avg == 0:
        return False
    return df["volume"].iloc[i] >= avg * mult


# ---------------------------------------------------------------------------
# 2) SPRING — phá đáy giả (bullish)
# ---------------------------------------------------------------------------
def detect_springs(df: pd.DataFrame, tr: TradingRange,
                   pierce: float = 0.002, vol_mult: float = 1.5) -> list[WyckoffSignal]:
    """
    Spring: trong vùng range, một nến có LOW thủng xuống dưới đáy range (quét
    stoploss) NHƯNG CLOSE quay lại trên đáy range -> phá đáy giả -> lực mua hấp
    thụ -> thiên hướng TĂNG.

    pierce: yêu cầu thủng tối thiểu (vd 0.2%) để loại nhiễu lẹt đẹt sát biên.
    """
    out = []
    low = df["low"].values
    close = df["close"].values
    floor = tr.bottom
    for i in range(tr.start, tr.end + 1):
        if low[i] < floor * (1 - pierce) and close[i] > floor:
            vs = _volume_spike(df, i, mult=vol_mult)
            out.append(WyckoffSignal(
                idx=i, kind="spring", price=float(low[i]), volume_spike=vs,
                note="Phá đáy giả (quét thanh khoản dưới đáy rồi đóng cửa lại trong range)."
                     + (" Volume cao xác nhận." if vs else "")))
    return out


# ---------------------------------------------------------------------------
# 3) UPTHRUST — phá đỉnh giả (bearish)
# ---------------------------------------------------------------------------
def detect_upthrusts(df: pd.DataFrame, tr: TradingRange,
                     pierce: float = 0.002, vol_mult: float = 1.5) -> list[WyckoffSignal]:
    """
    Upthrust: nến có HIGH vượt lên trên đỉnh range NHƯNG CLOSE quay lại dưới đỉnh
    -> phá đỉnh giả -> lực bán hấp thụ -> thiên hướng GIẢM.
    """
    out = []
    high = df["high"].values
    close = df["close"].values
    ceil = tr.top
    for i in range(tr.start, tr.end + 1):
        if high[i] > ceil * (1 + pierce) and close[i] < ceil:
            vs = _volume_spike(df, i, mult=vol_mult)
            out.append(WyckoffSignal(
                idx=i, kind="upthrust", price=float(high[i]), volume_spike=vs,
                note="Phá đỉnh giả (quét thanh khoản trên đỉnh rồi đóng cửa lại trong range)."
                     + (" Volume cao xác nhận." if vs else "")))
    return out


# ---------------------------------------------------------------------------
# 4) XÁC NHẬN bằng TEST (cốt lõi Wyckoff: spring/upthrust phải được test lại
#    với VOLUME THẤP -> chứng tỏ lực đối kháng đã cạn)
# ---------------------------------------------------------------------------
def confirm_with_test(df: pd.DataFrame, tr: TradingRange,
                      signals: list[WyckoffSignal], lookahead: int = 8,
                      tol: float = 0.004) -> None:
    """
    Sau spring/upthrust, tìm nến 'test': quay lại sát mức quét NHƯNG volume THẤP
    hơn cú quét -> lực đã cạn -> tín hiệu đáng tin hơn. Đánh dấu confirmed=True.
    (Sửa trực tiếp trong list signals.)
    """
    vol = df["volume"].values
    low = df["low"].values
    high = df["high"].values
    n = len(df)
    for s in signals:
        v0 = vol[s.idx]
        for j in range(s.idx + 1, min(n, s.idx + 1 + lookahead)):
            if s.kind == "spring":
                # test: chạm lại gần đáy spring, KHÔNG thủng sâu hơn, volume thấp hơn
                if low[j] <= s.price * (1 + tol) and low[j] >= s.price * (1 - tol) \
                        and vol[j] < v0:
                    s.confirmed = True; s.test_idx = j
                    s.note += " Đã có test volume thấp xác nhận."
                    break
            else:  # upthrust
                if high[j] >= s.price * (1 - tol) and high[j] <= s.price * (1 + tol) \
                        and vol[j] < v0:
                    s.confirmed = True; s.test_idx = j
                    s.note += " Đã có test volume thấp xác nhận."
                    break


# ---------------------------------------------------------------------------
# 5) CLIMAX — cao trào (SC: selling climax / BC: buying climax)
#    Nến volume CỰC cao + biên độ lớn tại biên range -> dấu hiệu đảo lớn
# ---------------------------------------------------------------------------
def detect_climax(df: pd.DataFrame, tr: TradingRange,
                  vol_mult: float = 2.5, lookback: int = 20) -> list[Climax]:
    out = []
    vol = df["volume"].values
    high = df["high"].values; low = df["low"].values; close = df["close"].values
    rng = (df["high"] - df["low"]).values
    for i in range(tr.start, tr.end + 1):
        lo = max(0, i - lookback)
        avg_v = df["volume"].iloc[lo:i].mean()
        avg_r = (df["high"] - df["low"]).iloc[lo:i].mean()
        if pd.isna(avg_v) or avg_v == 0 or pd.isna(avg_r) or avg_r == 0:
            continue
        big_vol = vol[i] >= avg_v * vol_mult
        big_rng = rng[i] >= avg_r * 1.8
        if not (big_vol and big_rng):
            continue
        # SC: rơi mạnh xuống gần/đáy range rồi đóng cửa hồi lên -> bullish
        if low[i] <= tr.bottom * 1.01 and close[i] > (low[i] + rng[i] * 0.4):
            out.append(Climax(idx=i, kind="sc", price=float(low[i]),
                              note="Selling Climax — bán tháo volume cực cao rồi hồi (dấu hiệu tạo đáy)."))
        # BC: đẩy mạnh lên gần/đỉnh range rồi đóng cửa rớt lại -> bearish
        elif high[i] >= tr.top * 0.99 and close[i] < (high[i] - rng[i] * 0.4):
            out.append(Climax(idx=i, kind="bc", price=float(high[i]),
                              note="Buying Climax — mua đuổi volume cực cao rồi rớt (dấu hiệu tạo đỉnh)."))
    return out


# ---------------------------------------------------------------------------
# 6) HẤP THỤ (effort vs result): volume rất cao nhưng giá đi được rất ít
#    -> tay to đang 'hấp thụ' lệnh -> manh mối có dòng tiền lớn âm thầm
# ---------------------------------------------------------------------------
def detect_absorption(df: pd.DataFrame, tr: TradingRange,
                      vol_mult: float = 2.0, lookback: int = 20) -> list[int]:
    out = []
    vol = df["volume"].values
    body = (df["close"] - df["open"]).abs().values
    for i in range(tr.start, tr.end + 1):
        lo = max(0, i - lookback)
        avg_v = df["volume"].iloc[lo:i].mean()
        avg_b = (df["close"] - df["open"]).abs().iloc[lo:i].mean()
        if pd.isna(avg_v) or avg_v == 0 or pd.isna(avg_b) or avg_b == 0:
            continue
        if vol[i] >= avg_v * vol_mult and body[i] <= avg_b * 0.6:
            out.append(i)      # nỗ lực lớn (volume) mà kết quả nhỏ (thân nến) = hấp thụ
    return out


# ---------------------------------------------------------------------------
# 7) Tổng hợp Wyckoff
# ---------------------------------------------------------------------------
def analyze_wyckoff(df: pd.DataFrame, window: int = 40,
                    climax_vol_mult: float = 2.5,
                    absorption_vol_mult: float = 2.0,
                    spike_mult: float = 1.5) -> WyckoffResult:
    """
    Tìm range gần nhất rồi đọc câu chuyện Wyckoff:
      - spring/upthrust (phá biên giả) + XÁC NHẬN bằng test volume thấp
      - climax (SC/BC) — cao trào volume cực cao tại biên
      - hấp thụ (effort vs result) — volume lớn mà giá đi ít
    Tổng hợp thành thiên hướng tích luỹ / phân phối, ưu tiên tín hiệu ĐÃ XÁC NHẬN.

    Độ nhạy (giảm = nhạy hơn, bắt nhiều tín hiệu hơn; tăng = chặt hơn):
        climax_vol_mult     : ngưỡng volume để coi là climax (mặc định 2.5x)
        absorption_vol_mult : ngưỡng volume để coi là nến hấp thụ (2.0x)
        spike_mult          : ngưỡng volume cao cho spring/upthrust (1.5x)
    """
    tr = find_trading_range(df, window=window)
    if tr is None:
        return WyckoffResult(None, [], "unclear",
                             "Không thấy vùng đi ngang rõ ràng — Wyckoff cần range để phân tích.")

    springs = detect_springs(df, tr, vol_mult=spike_mult)
    upthrusts = detect_upthrusts(df, tr, vol_mult=spike_mult)
    signals = sorted(springs + upthrusts, key=lambda s: s.idx)
    confirm_with_test(df, tr, signals)
    climaxes = detect_climax(df, tr, vol_mult=climax_vol_mult)
    absorption = detect_absorption(df, tr, vol_mult=absorption_vol_mult)

    # chấm điểm: tín hiệu mới hơn + volume cao + ĐÃ TEST -> nặng hơn nhiều
    score = 0.0
    for s in signals:
        recency = (s.idx - tr.start) / max(1, (tr.end - tr.start))
        w = (0.5 + recency)
        if s.volume_spike: w *= 1.3
        if s.confirmed:    w *= 2.0          # đã xác nhận -> trọng số gấp đôi
        score += w if s.kind == "spring" else -w
    # climax cộng thêm trọng số theo hướng
    for c in climaxes:
        score += 1.2 if c.kind == "sc" else -1.2

    n_conf = sum(1 for s in signals if s.confirmed)
    if score > 0.5:
        hint = "accumulation"
        note = "Nghiêng TÍCH LUỸ — spring/SC cho thấy lực mua hấp thụ, khả năng chuẩn bị TĂNG."
    elif score < -0.5:
        hint = "distribution"
        note = "Nghiêng PHÂN PHỐI — upthrust/BC cho thấy lực bán hấp thụ, khả năng chuẩn bị GIẢM."
    else:
        hint = "unclear"
        note = "Có range nhưng tín hiệu hai chiều cân bằng — chờ thêm xác nhận."

    # bổ sung chi tiết vào note
    extra = []
    if n_conf:        extra.append(f"{n_conf} tín hiệu đã được test xác nhận")
    if climaxes:      extra.append(f"{len(climaxes)} cao trào (climax)")
    if absorption:    extra.append(f"{len(absorption)} nến hấp thụ")
    if extra:
        note += "  •  " + ", ".join(extra) + "."

    return WyckoffResult(trading_range=tr, signals=signals, bias_hint=hint, note=note,
                         climaxes=climaxes, absorption=absorption)


# ---------------------------------------------------------------------------
# Tạo dữ liệu range giả để TEST (random walk hiếm khi tạo range đẹp)
# ---------------------------------------------------------------------------
def _make_accumulation(n_pre=30, n_range=45, n_post=20, seed=1) -> pd.DataFrame:
    """Sinh kịch bản: giảm -> đi ngang (dao động rõ + 1 spring) -> tăng, để test Wyckoff."""
    import numpy as np
    rng = np.random.default_rng(seed)
    rows, price = [], 120.0
    def push(o, target, vol, vmul=1.0):
        """đẩy giá về phía target để tạo dao động chạm biên."""
        c = o + (target - o) * (0.4 + rng.random() * 0.4) + (rng.random() - 0.5) * vol
        h = max(o, c) + rng.random() * 0.6
        l = min(o, c) - rng.random() * 0.6
        return o, h, l, c, (100 + rng.random() * 200) * vmul

    # downtrend dẫn vào
    for _ in range(n_pre):
        o = price; c = o - 0.6 + (rng.random() - 0.5) * 1.2
        h = max(o, c) + rng.random() * 0.6; l = min(o, c) - rng.random() * 0.6
        rows.append((o, h, l, c, 100 + rng.random() * 200)); price = c

    floor, ceil = price - 1, price + 9        # định nghĩa rõ sàn/trần range
    for k in range(n_range):
        target = ceil if (k // 4) % 2 == 0 else floor   # dao động lên xuống giữa 2 biên
        o, h, l, c, v = push(price, target, 1.4)
        if k == n_range - 6:                  # spring gần cuối: thủng sàn + volume cao rồi đóng lại
            l = floor - 5.0; c = floor + 0.8; h = max(o, c) + 0.5; v = 650
        rows.append((o, h, l, c, v)); price = c

    # bật tăng sau spring
    for _ in range(n_post):
        o = price; c = o + 1.0 + (rng.random() - 0.5) * 1.5
        h = max(o, c) + rng.random() * 0.6; l = min(o, c) - rng.random() * 0.6
        rows.append((o, h, l, c, 100 + rng.random() * 200)); price = c

    idx = pd.date_range("2024-01-01", periods=len(rows), freq="h", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=idx)
    df.index.name = "time"
    return df


if __name__ == "__main__":
    # Chạy thử: python -m smc.wyckoff
    df = _make_accumulation(seed=3)
    # phân tích quanh vùng range (bỏ đoạn tăng cuối để range còn "hiện")
    res = analyze_wyckoff(df.iloc[:-15], window=45)

    print("Thiên hướng Wyckoff:", res.bias_hint.upper())
    print("Nhận định:", res.note)
    if res.trading_range:
        tr = res.trading_range
        print(f"Trading range : {tr.bottom:.2f} – {tr.top:.2f}")
    print(f"Số tín hiệu   : {len(res.signals)}")
    for s in res.signals:
        tag = "🟢" if s.kind == "spring" else "🔴"
        print(f"  {tag} {s.kind:9} @ {s.price:.2f} | volume cao: {s.volume_spike} | {s.note}")
