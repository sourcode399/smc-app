"""
smc/engine.py — ENGINE SMC CORE (Phần 2)
=========================================
Đây là "trái tim" của app. Nhận vào DataFrame nến chuẩn (từ Phần 1) và phát hiện
các thành phần Smart Money Concepts:

    1) detect_swings()      -> swing high / swing low (fractal)
    2) analyze_structure()  -> BOS / CHoCH (phá vỡ & đảo cấu trúc)
    3) detect_fvg()         -> Fair Value Gap (vùng mất cân bằng)
    4) detect_order_blocks()-> Order Block (vùng smart money hay phản ứng)
    5) analyze()            -> chạy tất cả, trả về 1 object kết quả gọn

Mọi hàm KHÔNG vẽ vời gì, chỉ trả dữ liệu thuần (dataclass/list). Việc hiển thị
để dành cho Phần 7. Tách như vậy thì test & backtest dễ.

Quy ước index: dùng vị trí nguyên (0..n-1) để tham chiếu nến, vì dễ tính toán.
Muốn lấy timestamp thật thì map qua df.index[i].
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal
import pandas as pd


# ===========================================================================
# Các kiểu dữ liệu kết quả — rõ ràng, dễ đọc, dễ dùng ở phần sau
# ===========================================================================
@dataclass
class Swing:
    idx: int                       # vị trí nến
    price: float
    kind: Literal["high", "low"]
    broken: bool = False           # đã bị giá phá qua chưa

@dataclass
class StructureEvent:
    idx: int                       # nến nơi giá ĐÓNG CỬA phá mức
    level: float                   # mức bị phá (giá swing trước đó)
    direction: Literal["up", "down"]
    kind: Literal["BOS", "CHoCH"]  # BOS = theo trend, CHoCH = đảo trend

@dataclass
class FVG:
    idx: int                       # nến giữa của cụm 3 nến
    top: float
    bottom: float
    direction: Literal["up", "down"]
    mitigated: bool = False        # giá đã quay lại lấp gap chưa

@dataclass
class OrderBlock:
    idx: int                       # vị trí nến order block
    top: float
    bottom: float
    direction: Literal["up", "down"]   # up = bullish OB, down = bearish OB
    mitigated: bool = False

@dataclass
class Liquidity:
    """Vùng thanh khoản: cụm đỉnh/đáy bằng nhau — nơi stoploss đám đông tụ lại."""
    level: float
    side: Literal["buyside", "sellside"]   # buyside = trên (cụm đỉnh), sellside = dưới (cụm đáy)
    idxs: list                              # các swing tạo nên vùng này
    swept_at: int = -1                      # nến quét vùng này (-1 = chưa bị quét)

@dataclass
class Sweep:
    """Cú quét thanh khoản: phá vùng liquidity rồi đóng cửa lại -> bẫy giá."""
    idx: int
    level: float
    direction: Literal["up", "down"]   # up = quét đáy rồi bật lên (bullish);
                                        # down = quét đỉnh rồi rớt xuống (bearish)

@dataclass
class SMCResult:
    """Gói toàn bộ kết quả phân tích để truyền đi 1 cục."""
    swings: list[Swing] = field(default_factory=list)
    events: list[StructureEvent] = field(default_factory=list)
    fvgs: list[FVG] = field(default_factory=list)
    order_blocks: list[OrderBlock] = field(default_factory=list)
    liquidity: list[Liquidity] = field(default_factory=list)
    sweeps: list[Sweep] = field(default_factory=list)
    trend: int = 0                 # 1 = tăng, -1 = giảm, 0 = chưa rõ


# ===========================================================================
# 1) SWING HIGH / LOW  (fractal với lookback L)
# ===========================================================================
def detect_swings(df: pd.DataFrame, lookback: int = 2,
                  min_atr_mult: float = 1.0) -> list[Swing]:
    """
    Swing high: đỉnh cao hơn `lookback` nến hai bên.
    Swing low : đáy thấp hơn `lookback` nến hai bên.

    lookback     : nhỏ (1-2) -> nhạy; lớn (3-5) -> chỉ bắt swing lớn.
    min_atr_mult : lọc swing vụn theo biên độ ATR (0 = tắt lọc). Tăng lên để
                   biểu đồ bớt rối. Đây là nền tảng: BOS/CHoCH & OB dựa vào swing.
    """
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    swings: list[Swing] = []

    for i in range(lookback, n - lookback):
        win = range(i - lookback, i + lookback + 1)
        is_high = all(highs[j] <= highs[i] for j in win if j != i)
        is_low  = all(lows[j]  >= lows[i]  for j in win if j != i)
        if is_high:
            swings.append(Swing(idx=i, price=float(highs[i]), kind="high"))
        if is_low:
            swings.append(Swing(idx=i, price=float(lows[i]), kind="low"))

    swings.sort(key=lambda s: s.idx)
    if min_atr_mult > 0:
        swings = filter_swings(df, swings, min_atr_mult=min_atr_mult)
    return swings


# ---------------------------------------------------------------------------
# ATR (Average True Range) — thước đo biến động, dùng để lọc swing theo độ lớn
# ---------------------------------------------------------------------------
def _atr(df: pd.DataFrame, period: int = 14):
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean().values


def filter_swings(df: pd.DataFrame, swings: list[Swing],
                  min_atr_mult: float = 1.0) -> list[Swing]:
    """
    Lọc swing vụn (kiểu zigzag) để bỏ nhiễu:
      - Bắt buộc swing XEN KẼ high/low (2 high liền nhau -> giữ cái cao hơn).
      - Một đảo chiều chỉ được tính nếu biên độ >= min_atr_mult * ATR tại đó.

    Đây là chìa khoá làm biểu đồ bớt rối: chỉ giữ swing ĐÁNG KỂ, nhờ đó BOS/CHoCH
    và Order Block cũng giảm hẳn. Tăng min_atr_mult -> lọc mạnh hơn (ít swing hơn).
    """
    if not swings:
        return swings
    atr = _atr(df)
    out: list[Swing] = []
    for s in swings:
        if not out:
            out.append(s)
            continue
        last = out[-1]
        if s.kind == last.kind:
            # cùng loại liền nhau -> giữ cái cực trị hơn
            if (s.kind == "high" and s.price > last.price) or \
               (s.kind == "low" and s.price < last.price):
                out[-1] = s
        else:
            move = abs(s.price - last.price)
            thr = atr[s.idx] * min_atr_mult
            if move >= thr:
                out.append(s)        # đảo chiều đủ lớn -> giữ
            # nếu nhỏ hơn ngưỡng -> bỏ qua (coi như nhiễu)
    return out
def analyze_structure(df: pd.DataFrame, swings: list[Swing]):
    """
    Quét theo thời gian. Mỗi khi giá ĐÓNG CỬA vượt swing high gần nhất -> phá lên;
    đóng cửa thủng swing low gần nhất -> phá xuống.

        - Nếu phá CÙNG chiều trend đang chạy  -> BOS  (tiếp diễn)
        - Nếu phá NGƯỢC chiều trend đang chạy -> CHoCH (đảo chiều — tín hiệu mạnh)

    Trả về (events, trend_cuối_cùng).
    Lưu ý: mỗi swing chỉ tính phá 1 lần (đánh dấu broken) để khỏi đếm trùng.
    """
    close = df["close"].values
    n = len(df)
    events: list[StructureEvent] = []
    trend = 0

    # bản sao để đánh dấu broken mà không đụng dữ liệu gốc của caller
    sw = [Swing(s.idx, s.price, s.kind) for s in swings]

    def last_unbroken(kind: str, before: int):
        cand = [s for s in sw if s.kind == kind and s.idx < before and not s.broken]
        return cand[-1] if cand else None

    for i in range(n):
        hi = last_unbroken("high", i)
        if hi and close[i] > hi.price:
            kind = "CHoCH" if trend == -1 else "BOS"
            events.append(StructureEvent(i, hi.price, "up", kind))
            hi.broken = True
            trend = 1

        lo = last_unbroken("low", i)
        if lo and close[i] < lo.price:
            kind = "CHoCH" if trend == 1 else "BOS"
            events.append(StructureEvent(i, lo.price, "down", kind))
            lo.broken = True
            trend = -1

    return events, trend


# ===========================================================================
# 3) FAIR VALUE GAP (imbalance 3 nến)
# ===========================================================================
def detect_fvg(df: pd.DataFrame) -> list[FVG]:
    """
    Bullish FVG: low của nến (i+1) > high của nến (i-1)  -> còn "khoảng trống" phía dưới
    Bearish FVG: high của nến (i+1) < low của nến (i-1)
    Sau đó kiểm tra giá có quay lại lấp (mitigate) chưa.
    """
    high = df["high"].values
    low = df["low"].values
    n = len(df)
    fvgs: list[FVG] = []

    for i in range(1, n - 1):
        if low[i + 1] > high[i - 1]:
            fvgs.append(FVG(i, top=float(low[i + 1]), bottom=float(high[i - 1]), direction="up"))
        elif high[i + 1] < low[i - 1]:
            fvgs.append(FVG(i, top=float(low[i - 1]), bottom=float(high[i + 1]), direction="down"))

    # đánh dấu đã bị lấp chưa: nến sau chạm vào khoảng gap
    for g in fvgs:
        for k in range(g.idx + 2, n):
            if low[k] <= g.top and high[k] >= g.bottom:
                g.mitigated = True
                break
    return fvgs


# ===========================================================================
# 4) ORDER BLOCK
# ===========================================================================
def detect_order_blocks(df: pd.DataFrame,
                        events: list[StructureEvent],
                        max_lookback: int = 8) -> list[OrderBlock]:
    """
    Bullish OB: nến GIẢM cuối cùng ngay trước cú đẩy tăng tạo ra BOS/CHoCH lên.
    Bearish OB: nến TĂNG cuối cùng ngay trước cú đẩy giảm.

    Đây là vùng giá mà "smart money" được cho là đã đặt lệnh, nên giá thường
    phản ứng khi quay lại. Ta dò ngược tối đa `max_lookback` nến từ điểm phá vỡ.
    """
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    obs: list[OrderBlock] = []
    seen: set = set()                           # tránh thêm trùng cùng 1 nến/chiều

    for ev in events:
        start = ev.idx - 1
        stop = max(0, ev.idx - max_lookback)
        if ev.direction == "up":
            for k in range(start, stop - 1, -1):
                if c[k] < o[k]:                         # nến giảm cuối trước cú đẩy
                    if (k, "up") not in seen:
                        obs.append(OrderBlock(k, top=float(max(o[k], h[k])),
                                              bottom=float(min(c[k], l[k])), direction="up"))
                        seen.add((k, "up"))
                    break
        else:
            for k in range(start, stop - 1, -1):
                if c[k] > o[k]:                         # nến tăng cuối trước cú đẩy
                    if (k, "down") not in seen:
                        obs.append(OrderBlock(k, top=float(max(c[k], h[k])),
                                              bottom=float(min(o[k], l[k])), direction="down"))
                        seen.add((k, "down"))
                    break

    # đánh dấu OB đã bị giá quay lại chạm chưa (mitigated).
    # QUAN TRỌNG: phải đợi giá RỜI KHỎI vùng OB trước (cú đẩy đi xa), rồi mới
    # tính lần QUAY LẠI là mitigation. Nếu không, chính cây nến cú đẩy sẽ bị
    # tính nhầm là "đã chạm" -> mọi OB đều mitigated ngay (bug).
    n = len(df)
    for ob in obs:
        left_zone = False                       # giá đã rời khỏi vùng OB chưa?
        for k in range(ob.idx + 1, n):
            if ob.direction == "up":
                if not left_zone:
                    if l[k] > ob.top:           # giá đã đẩy lên hẳn trên OB
                        left_zone = True
                elif l[k] <= ob.top:            # quay lại tap vào OB
                    ob.mitigated = True
                    break
            else:  # bearish OB
                if not left_zone:
                    if h[k] < ob.bottom:        # giá đã đẩy xuống hẳn dưới OB
                        left_zone = True
                elif h[k] >= ob.bottom:         # quay lại tap vào OB
                    ob.mitigated = True
                    break
    return obs


# ===========================================================================
# 5b) LIQUIDITY (thanh khoản) + SWEEP (quét thanh khoản)
# ===========================================================================
def detect_liquidity(df: pd.DataFrame, swings: list[Swing],
                     tol_atr: float = 0.5) -> list[Liquidity]:
    """
    Tìm vùng thanh khoản = cụm đỉnh (hoặc đáy) BẰNG NHAU (chênh nhau < tol_atr*ATR).
    Đây là nơi stoploss của đám đông tụ lại -> tay to hay "quét" qua để gom lệnh.

        buyside  : cụm SWING HIGH gần bằng nhau (thanh khoản phía trên)
        sellside : cụm SWING LOW  gần bằng nhau (thanh khoản phía dưới)
    """
    atr = _atr(df)
    pools: list[Liquidity] = []
    for kind, side in [("high", "buyside"), ("low", "sellside")]:
        pts = [s for s in swings if s.kind == kind]
        used = [False] * len(pts)
        for a in range(len(pts)):
            if used[a]:
                continue
            group = [pts[a]]
            for b in range(a + 1, len(pts)):
                if used[b]:
                    continue
                tol = atr[pts[b].idx] * tol_atr
                if abs(pts[b].price - pts[a].price) <= tol:
                    group.append(pts[b]); used[b] = True
            if len(group) >= 2:                    # ít nhất 2 điểm bằng nhau mới là pool
                used[a] = True
                level = sum(g.price for g in group) / len(group)
                pools.append(Liquidity(level=float(level), side=side,
                                       idxs=[g.idx for g in group]))
    return pools


def detect_sweeps(df: pd.DataFrame, pools: list[Liquidity],
                  pierce: float = 0.0005) -> list[Sweep]:
    """
    Cú quét: nến phá QUA vùng liquidity rồi ĐÓNG CỬA quay lại (bẫy giá).
        - quét buyside (đỉnh) rồi đóng dưới  -> bearish sweep (direction='down')
        - quét sellside (đáy) rồi đóng trên  -> bullish sweep (direction='up')
    Đánh dấu pool đã bị quét (swept_at) để biết vùng nào "đã ăn".
    """
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    n = len(df)
    sweeps: list[Sweep] = []
    for pool in pools:
        first_idx = min(pool.idxs)
        for i in range(first_idx + 1, n):
            if pool.side == "buyside":
                if high[i] > pool.level * (1 + pierce) and close[i] < pool.level:
                    sweeps.append(Sweep(idx=i, level=pool.level, direction="down"))
                    pool.swept_at = i; break
            else:  # sellside
                if low[i] < pool.level * (1 - pierce) and close[i] > pool.level:
                    sweeps.append(Sweep(idx=i, level=pool.level, direction="up"))
                    pool.swept_at = i; break
    return sweeps


# ===========================================================================
# 6) HÀM TỔNG — chạy tất cả
# ===========================================================================
def analyze(df: pd.DataFrame, lookback: int = 2, min_atr_mult: float = 1.0) -> SMCResult:
    """Chạy toàn bộ pipeline SMC, trả về 1 SMCResult gọn cho phần sau dùng.

    min_atr_mult: mức lọc swing vụn (mặc định 1.0). Tăng -> ít tín hiệu, sạch hơn.
    """
    swings = detect_swings(df, lookback=lookback, min_atr_mult=min_atr_mult)
    events, trend = analyze_structure(df, swings)
    fvgs = detect_fvg(df)
    obs = detect_order_blocks(df, events)
    pools = detect_liquidity(df, swings)
    sweeps = detect_sweeps(df, pools)
    return SMCResult(swings=swings, events=events, fvgs=fvgs, order_blocks=obs,
                     liquidity=pools, sweeps=sweeps, trend=trend)


if __name__ == "__main__":
    # Chạy thử: python -m smc.engine
    from smc.data import make_synthetic
    df = make_synthetic(300, seed=7)
    res = analyze(df, lookback=2)

    n_high = sum(1 for s in res.swings if s.kind == "high")
    n_low = sum(1 for s in res.swings if s.kind == "low")
    n_bos = sum(1 for e in res.events if e.kind == "BOS")
    n_ch = sum(1 for e in res.events if e.kind == "CHoCH")
    fvg_open = sum(1 for g in res.fvgs if not g.mitigated)

    print(f"Tổng nến        : {len(df)}")
    print(f"Swings          : {n_high} high / {n_low} low")
    print(f"Cấu trúc        : {n_bos} BOS / {n_ch} CHoCH")
    print(f"FVG             : {len(res.fvgs)} (còn mở: {fvg_open})")
    print(f"Order Blocks    : {len(res.order_blocks)}")
    print(f"Trend hiện tại  : {'TĂNG' if res.trend==1 else 'GIẢM' if res.trend==-1 else 'TRUNG LẬP'}")

    print("\n5 sự kiện cấu trúc gần nhất:")
    for e in res.events[-5:]:
        t = df.index[e.idx].strftime("%m-%d %H:%M")
        print(f"  [{t}] {e.kind:5} {e.direction:4} @ {e.level:.2f}")
