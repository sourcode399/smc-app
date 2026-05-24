"""
smc/confluence.py — CHẤM ĐIỂM HỢP LƯU (Confluence)
====================================================
Kiểm tra 6 yếu tố hợp lưu theo chiều bias khung lớn. Càng nhiều yếu tố trùng
nhau cùng một hướng -> kèo càng chất. Mục đích: LỌC bớt kèo rác, không phải
để vào nhiều.

6 yếu tố (đánh giá theo chiều bias):
    1. Khung lớn cùng hướng (HTF trend)
    2. Giá gần vùng hỗ trợ/kháng cự mạnh (Order Block còn hiệu lực)
    3. Vùng đó trùng FVG chưa lấp
    4. Vừa có cú quét thanh khoản (sweep) cùng chiều
    5. RSI vừa thoát vùng quá bán/quá mua
    6. Có nến đảo chiều (engulfing / pin bar) gần đây

LƯU Ý: điểm cao KHÔNG đảm bảo thắng — chỉ là kèo "đáng cân nhắc" hơn. Vẫn phải
quản lý vốn + backtest.
"""

from __future__ import annotations
from dataclasses import dataclass
import pandas as pd


@dataclass
class Factor:
    name: str
    passed: bool
    note: str


# ---------------------------------------------------------------------------
# RSI (Relative Strength Index)
# ---------------------------------------------------------------------------
def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - 100 / (1 + rs)


# ---------------------------------------------------------------------------
# Nến đảo chiều: engulfing & pin bar
# ---------------------------------------------------------------------------
def _is_bullish_reversal(df: pd.DataFrame, i: int) -> bool:
    o, h, l, c = (df["open"].iloc[i], df["high"].iloc[i],
                  df["low"].iloc[i], df["close"].iloc[i])
    body = abs(c - o)
    rng = h - l
    if rng <= 0:
        return False
    # pin bar tăng (hammer): râu dưới dài, thân nhỏ, đóng cửa nửa trên
    lower_wick = min(o, c) - l
    if lower_wick >= 2 * body and (c - l) >= 0.6 * rng:
        return True
    # bullish engulfing: nến trước giảm, nến này tăng và bao trùm thân
    if i > 0:
        po, pc = df["open"].iloc[i - 1], df["close"].iloc[i - 1]
        if pc < po and c > o and c >= po and o <= pc:
            return True
    return False


def _is_bearish_reversal(df: pd.DataFrame, i: int) -> bool:
    o, h, l, c = (df["open"].iloc[i], df["high"].iloc[i],
                  df["low"].iloc[i], df["close"].iloc[i])
    body = abs(c - o)
    rng = h - l
    if rng <= 0:
        return False
    # pin bar giảm (shooting star): râu trên dài, thân nhỏ, đóng cửa nửa dưới
    upper_wick = h - max(o, c)
    if upper_wick >= 2 * body and (h - c) >= 0.6 * rng:
        return True
    # bearish engulfing
    if i > 0:
        po, pc = df["open"].iloc[i - 1], df["close"].iloc[i - 1]
        if pc > po and c < o and c <= po and o >= pc:
            return True
    return False


# ---------------------------------------------------------------------------
# Chấm điểm hợp lưu
# ---------------------------------------------------------------------------
@dataclass
class ConfluenceResult:
    direction: str            # 'LONG' / 'SHORT' / '—'
    factors: list             # list[Factor]
    score: int                # số yếu tố đạt
    total: int                # tổng yếu tố (6)
    verdict: str

    def summary(self) -> str:
        lines = [f"Hợp lưu cho {self.direction}: {self.score}/{self.total}"]
        for f in self.factors:
            mark = "✅" if f.passed else "⬜"
            lines.append(f"  {mark} {f.name}{(' — ' + f.note) if f.note else ''}")
        lines.append(self.verdict)
        return "\n".join(lines)


def score_confluence(df: pd.DataFrame, res, decision,
                     recent: int = 6) -> ConfluenceResult:
    """
    Chấm điểm 6 yếu tố hợp lưu theo chiều bias.

        df       : DataFrame nến (đã có volume)
        res      : SMCResult (engine.analyze)
        decision : Decision (decision.decide)
        recent   : số nến gần nhất coi là "vừa xảy ra"
    """
    bias = decision.bias
    if bias == "neutral":
        return ConfluenceResult("—", [], 0, 6,
                                "Khung lớn chưa rõ hướng — chưa nên đánh giá hợp lưu.")
    direction = "LONG" if bias == "bull" else "SHORT"
    want = "up" if bias == "bull" else "down"
    n = len(df)
    last = float(df["close"].iloc[-1])
    factors: list[Factor] = []

    # 1. Khung lớn cùng hướng
    factors.append(Factor("Khung lớn cùng hướng",
                          decision.aligned,
                          "khung nhỏ đang thuận khung lớn" if decision.aligned
                          else "khung nhỏ chưa thuận khung lớn"))

    # 2. Giá gần Order Block còn hiệu lực (cùng chiều)
    near_ob = None
    for ob in res.order_blocks:
        if ob.direction == want and not ob.mitigated:
            mid = (ob.top + ob.bottom) / 2
            if abs(mid - last) / last <= 0.03:        # trong 3% so với giá
                near_ob = ob
                break
    factors.append(Factor("Giá gần Order Block mạnh", near_ob is not None,
                          "có OB còn tươi gần giá" if near_ob else "không có OB gần"))

    # 3. OB đó trùng FVG chưa lấp
    fvg_overlap = False
    if near_ob:
        for g in res.fvgs:
            if g.mitigated or g.direction != want:
                continue
            # hai vùng có giao nhau không
            if not (g.bottom > near_ob.top or g.top < near_ob.bottom):
                fvg_overlap = True
                break
    factors.append(Factor("Trùng FVG chưa lấp", fvg_overlap,
                          "OB trùng vùng FVG" if fvg_overlap else "không trùng FVG"))

    # 4. Vừa có cú quét thanh khoản cùng chiều
    recent_sweep = any(s.direction == want and s.idx >= n - recent for s in res.sweeps)
    factors.append(Factor("Cú quét thanh khoản gần đây", recent_sweep,
                          "có sweep cùng chiều" if recent_sweep else "chưa có sweep"))

    # 5. RSI vừa thoát vùng quá bán/quá mua
    r = rsi(df["close"])
    rsi_ok = False
    rsi_note = ""
    if len(r) >= recent + 1:
        window = r.iloc[-recent:]
        if bias == "bull":
            rsi_ok = (window.min() < 35) and (r.iloc[-1] > 35)   # thoát quá bán
            rsi_note = f"RSI {r.iloc[-1]:.0f}, vừa thoát quá bán" if rsi_ok else f"RSI {r.iloc[-1]:.0f}"
        else:
            rsi_ok = (window.max() > 65) and (r.iloc[-1] < 65)   # thoát quá mua
            rsi_note = f"RSI {r.iloc[-1]:.0f}, vừa thoát quá mua" if rsi_ok else f"RSI {r.iloc[-1]:.0f}"
    factors.append(Factor("RSI thoát vùng cực trị", rsi_ok, rsi_note))

    # 6. Nến đảo chiều gần đây
    rev = False
    for i in range(max(1, n - recent), n):
        if (bias == "bull" and _is_bullish_reversal(df, i)) or \
           (bias == "bear" and _is_bearish_reversal(df, i)):
            rev = True
            break
    factors.append(Factor("Nến đảo chiều", rev,
                          "có nến đảo chiều cùng hướng" if rev else "chưa có"))

    score = sum(1 for f in factors if f.passed)
    if score >= 4:
        verdict = f"→ Hợp lưu MẠNH ({score}/6) — kèo {direction} đáng cân nhắc."
    elif score >= 3:
        verdict = f"→ Hợp lưu KHÁ ({score}/6) — cân nhắc thận trọng."
    else:
        verdict = f"→ Hợp lưu YẾU ({score}/6) — nên đứng ngoài, chờ thêm xác nhận."

    return ConfluenceResult(direction, factors, score, 6, verdict)


if __name__ == "__main__":
    from smc.data import make_synthetic
    from smc.engine import analyze
    from smc.decision import decide
    df = make_synthetic(220, seed=3)
    res = analyze(df, 3, 1.5)
    d = decide(df, "4h", 3, 1.5)
    print(score_confluence(df, res, d).summary())
