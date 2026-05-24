"""
smc/scanner.py — QUÉT NHIỀU MÃ (Confluence Scanner)
=====================================================
Thay vì soi từng mã, quét cả danh sách rồi xếp hạng theo điểm hợp lưu. Mã nào
điểm cao = đang hội tụ nhiều yếu tố = đáng nhìn kỹ.

Dùng kèm st.progress trong app để hiện tiến độ (vì quét nhiều mã hơi lâu do mỗi
mã phải tải dữ liệu riêng).
"""

from __future__ import annotations

from smc.data import get_candles
from smc.engine import analyze
from smc.decision import decide
from smc.confluence import score_confluence


def scan_one(name: str, market: str, symbol: str,
             timeframe: str = "1h", htf_rule: str = "4h",
             lookback: int = 3, min_atr: float = 1.5,
             require_sweep: bool = False, min_rr: float = 0.0) -> dict | None:
    """
    Quét MỘT mã -> trả về dict kết quả, hoặc None nếu lỗi (mã sai / không có mạng).

    Trả về: tên, mã, bias, điểm hợp lưu, hướng lệnh (nếu có), R:R.
    """
    try:
        df = get_candles(market, symbol, timeframe)
        if df is None or len(df) < 60:
            return None
        res = analyze(df, lookback=lookback, min_atr_mult=min_atr)
        d = decide(df, htf_rule=htf_rule, lookback=lookback,
                   min_atr_mult=min_atr, require_sweep=require_sweep, min_rr=min_rr)
        c = score_confluence(df, res, d)

        bias_vn = {"bull": "🟢 Tăng", "bear": "🔴 Giảm", "neutral": "🟡 Trung lập"}[d.bias]
        p = d.plan
        return {
            "Mã": name,
            "Bias": bias_vn,
            "Hợp lưu": f"{c.score}/6" if c.direction != "—" else "—",
            "_score": c.score,
            "Hướng": c.direction if c.direction != "—" else "—",
            "Có lệnh": "✅" if p else "—",
            "R:R": p.rr if p else None,
            "Giá": float(df["close"].iloc[-1]),
            # giá kế hoạch (số thô, app sẽ tự định dạng); None nếu chưa có lệnh
            "_entry_top": float(p.entry_top) if p else None,
            "_entry_bottom": float(p.entry_bottom) if p else None,
            "_sl": float(p.stoploss) if p else None,
            "_tp": float(p.takeprofit) if p else None,
        }
    except Exception:
        return None      # mã lỗi -> bỏ qua, không làm vỡ cả lần quét


def rank(rows: list[dict]) -> list[dict]:
    """Xếp hạng: ưu tiên điểm hợp lưu cao, rồi tới có lệnh, rồi R:R cao."""
    return sorted(
        rows,
        key=lambda r: (r["_score"], 1 if r["Có lệnh"] == "✅" else 0, r["R:R"] or 0),
        reverse=True)
