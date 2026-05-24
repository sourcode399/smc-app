"""
smc/mtf.py — MULTI-TIMEFRAME (Phần 3)
======================================
Phối hợp 2 khung thời gian để lọc tín hiệu:

    - HTF (Higher Time Frame) = khung lớn  -> quyết định BIAS (hướng chính)
    - LTF (Lower Time Frame)  = khung nhỏ  -> tìm ĐIỂM VÀO khi thuận chiều HTF

Nguyên tắc "top-down": chỉ LONG ở khung nhỏ khi khung lớn đang TĂNG, chỉ SHORT
khi khung lớn đang GIẢM. Tín hiệu khung nhỏ ngược chiều khung lớn -> bỏ qua.

Cách lấy 2 khung:
    Cách A (1 lần fetch): lấy khung nhỏ rồi resample lên khung lớn  -> dùng ở đây.
    Cách B (2 lần fetch): gọi get_candles 2 lần với 2 timeframe khác nhau.
Cách A tiện vì 2 khung luôn khớp nhau tuyệt đối, không lệch dữ liệu.
"""

from __future__ import annotations
from dataclasses import dataclass
import pandas as pd

from smc.engine import analyze, SMCResult, OrderBlock, FVG


# ---------------------------------------------------------------------------
# Resample nến khung nhỏ -> khung lớn
# ---------------------------------------------------------------------------
def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Gộp nến nhỏ thành nến lớn đúng kiểu OHLCV.
        open  = giá mở của nến đầu trong nhóm
        high  = max
        low   = min
        close = giá đóng của nến cuối
        volume= tổng

    rule theo pandas offset: '4h', '1D', '1W', '15min', ...
    Ví dụ: df khung 1h -> resample_ohlcv(df, '4h') ra khung 4h.
    """
    agg = {"open": "first", "high": "max", "low": "min",
           "close": "last", "volume": "sum"}
    out = df.resample(rule, label="left", closed="left").agg(agg)
    return out.dropna()


# ---------------------------------------------------------------------------
# Map vùng HTF (order block / FVG) về mốc thời gian để dùng trên LTF
# ---------------------------------------------------------------------------
def _htf_zones(htf_df: pd.DataFrame, htf_res: SMCResult):
    """Trích các vùng quan trọng từ HTF kèm timestamp + khoảng giá (top/bottom)."""
    zones = []
    for ob in htf_res.order_blocks:
        if not ob.mitigated:                     # ưu tiên vùng chưa bị chạm
            zones.append({
                "type": "OB", "direction": ob.direction,
                "time": htf_df.index[ob.idx],
                "top": ob.top, "bottom": ob.bottom,
            })
    for g in htf_res.fvgs:
        if not g.mitigated:
            zones.append({
                "type": "FVG", "direction": g.direction,
                "time": htf_df.index[g.idx],
                "top": g.top, "bottom": g.bottom,
            })
    return zones


# ---------------------------------------------------------------------------
# Kết quả multi-timeframe
# ---------------------------------------------------------------------------
@dataclass
class MTFResult:
    htf_df: pd.DataFrame
    ltf_df: pd.DataFrame
    htf: SMCResult              # phân tích SMC khung lớn
    ltf: SMCResult              # phân tích SMC khung nhỏ
    htf_zones: list             # vùng HTF (OB/FVG) chưa mitigate
    aligned: bool               # 2 khung có cùng hướng không
    bias: str                   # 'bull' / 'bear' / 'neutral' (theo HTF)
    note: str                   # diễn giải ngắn


# ---------------------------------------------------------------------------
# Hàm chính
# ---------------------------------------------------------------------------
def analyze_mtf(ltf_df: pd.DataFrame,
                htf_rule: str = "4h",
                lookback: int = 2,
                min_atr_mult: float = 1.0) -> MTFResult:
    """
    Phân tích đồng thời 2 khung từ 1 DataFrame khung nhỏ.

        ltf_df   : nến khung nhỏ (vd 1h)
        htf_rule : quy tắc gộp lên khung lớn (vd '4h', '1D')

    Trả về MTFResult: bias lấy theo HTF, cờ aligned cho biết khung nhỏ có
    đang đi cùng hướng khung lớn hay không.
    """
    htf_df = resample_ohlcv(ltf_df, htf_rule)

    htf_res = analyze(htf_df, lookback=lookback, min_atr_mult=min_atr_mult)
    ltf_res = analyze(ltf_df, lookback=lookback, min_atr_mult=min_atr_mult)

    # bias theo khung lớn
    bias = "bull" if htf_res.trend == 1 else "bear" if htf_res.trend == -1 else "neutral"

    # 2 khung có đồng thuận không (cùng dấu trend)
    aligned = (htf_res.trend != 0 and htf_res.trend == ltf_res.trend)

    if htf_res.trend == 0:
        note = "Khung lớn chưa rõ hướng — nên đứng ngoài, chờ cấu trúc rõ ràng."
    elif aligned:
        note = (f"Khung lớn {'TĂNG' if bias=='bull' else 'GIẢM'} và khung nhỏ "
                f"đang đi cùng chiều — môi trường thuận lợi tìm điểm vào.")
    else:
        note = (f"Khung lớn {'TĂNG' if bias=='bull' else 'GIẢM'} nhưng khung nhỏ "
                f"đang ngược chiều — chờ khung nhỏ đảo lại (CHoCH) thuận theo khung lớn.")

    zones = _htf_zones(htf_df, htf_res)

    return MTFResult(htf_df=htf_df, ltf_df=ltf_df,
                     htf=htf_res, ltf=ltf_res,
                     htf_zones=zones, aligned=aligned,
                     bias=bias, note=note)


def ltf_entries_in_htf_zone(mtf: MTFResult, tolerance: float = 0.0):
    """
    Lọc Order Block khung nhỏ nằm TRONG vùng HTF cùng chiều bias — đây là điểm
    "confluence" (hợp lưu) chất lượng cao nhất: vùng tay to khung lớn + tín hiệu
    khớp ở khung nhỏ.

    tolerance: nới rộng vùng HTF thêm % (vd 0.001 = 0.1%) cho dễ khớp.
    Trả về list các OB khung nhỏ thoả điều kiện.
    """
    want = "up" if mtf.bias == "bull" else "down" if mtf.bias == "bear" else None
    if want is None:
        return []

    good = []
    for ob in mtf.ltf.order_blocks:
        if ob.direction != want or ob.mitigated:
            continue
        ob_mid = (ob.top + ob.bottom) / 2
        for z in mtf.htf_zones:
            if z["direction"] != want:
                continue
            lo = z["bottom"] * (1 - tolerance)
            hi = z["top"] * (1 + tolerance)
            if lo <= ob_mid <= hi:               # OB khung nhỏ nằm trong vùng HTF
                good.append(ob)
                break
    return good


if __name__ == "__main__":
    # Chạy thử: python -m smc.mtf
    from smc.data import make_synthetic

    # tạo nến "1h" rồi gộp lên "4h"
    ltf = make_synthetic(600, seed=11)
    mtf = analyze_mtf(ltf, htf_rule="4h", lookback=2)

    print(f"Khung nhỏ : {len(mtf.ltf_df)} nến")
    print(f"Khung lớn : {len(mtf.htf_df)} nến (gộp 4h)")
    print(f"Bias (HTF): {mtf.bias.upper()}")
    print(f"Đồng thuận: {'CÓ' if mtf.aligned else 'KHÔNG'}")
    print(f"Nhận định : {mtf.note}")
    print(f"Vùng HTF chưa chạm: {len(mtf.htf_zones)}")

    conf = ltf_entries_in_htf_zone(mtf, tolerance=0.002)
    print(f"\nĐiểm hợp lưu (OB khung nhỏ nằm trong vùng khung lớn): {len(conf)}")
    for ob in conf[-3:]:
        t = mtf.ltf_df.index[ob.idx].strftime("%m-%d %H:%M")
        print(f"  [{t}] OB {ob.direction} @ {ob.bottom:.2f}–{ob.top:.2f}")
