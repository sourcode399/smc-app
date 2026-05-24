"""
smc/decision.py — LOGIC RA QUYẾT ĐỊNH (Phần 4)
================================================
Gom mọi thứ từ Phần 2 & 3 thành MỘT nhận định hoàn chỉnh mà con người đọc được:

    - bias (hướng chính)            -> từ multi-timeframe
    - phát hiện VÙNG GIẰNG CO        -> detect_range()  (sideway = không vào lệnh)
    - kế hoạch vào lệnh cụ thể       -> build_plan()    (entry / SL / TP / R:R)
    - nhận định bằng tiếng Việt      -> decide() trả Decision + .summary()

Triết lý quan trọng: thà KHÔNG có lệnh còn hơn lệnh xấu. Nếu thị trường đi
ngang, hoặc 2 khung không đồng thuận, hoặc không có vùng vào hợp lệ -> trả về
"đứng ngoài". App tốt là app biết nói "chưa vào", không phải app lúc nào cũng
phun ra tín hiệu.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd

from smc.mtf import analyze_mtf, ltf_entries_in_htf_zone, MTFResult
from smc.engine import OrderBlock, _atr


# ===========================================================================
# 1) PHÁT HIỆN VÙNG GIẰNG CO (range / sideway)
# ===========================================================================
@dataclass
class Range:
    start: int
    end: int
    top: float
    bottom: float

def detect_range(df: pd.DataFrame,
                 window: int = 20,
                 max_width_pct: float = 0.06,
                 min_touches: int = 3) -> Optional[Range]:
    """
    Xác định cửa sổ `window` nến GẦN NHẤT có phải vùng giằng co không.

    Tiêu chí (đơn giản, dễ hiểu):
      - Biên độ vùng (đỉnh-đáy)/giá < max_width_pct (vd 6%)  -> giá bị "kẹp"
      - Giá chạm gần biên trên & biên dưới nhiều lần          -> dao động qua lại
    Nếu thoả -> trả về Range (vùng giằng co); ngược lại None.

    Đây là cảnh báo "đừng đánh breakout giả" — trong range, tín hiệu BOS/OB
    rất dễ là nhiễu.
    """
    if len(df) < window:
        return None
    seg = df.iloc[-window:]
    top = float(seg["high"].max())
    bottom = float(seg["low"].min())
    mid = (top + bottom) / 2
    if mid <= 0:
        return None

    width_pct = (top - bottom) / mid
    if width_pct > max_width_pct:
        return None                              # biên quá rộng -> đang trend, không phải range

    # đếm số lần chạm gần biên (trong 20% mép trên/dưới)
    band = (top - bottom) * 0.2
    touch_top = (seg["high"] >= top - band).sum()
    touch_bot = (seg["low"] <= bottom + band).sum()
    if touch_top >= min_touches and touch_bot >= min_touches:
        return Range(start=len(df) - window, end=len(df) - 1, top=top, bottom=bottom)
    return None


# ===========================================================================
# 2) KẾ HOẠCH VÀO LỆNH
# ===========================================================================
@dataclass
class Plan:
    direction: str          # 'LONG' / 'SHORT'
    entry_top: float
    entry_bottom: float
    stoploss: float
    takeprofit: float       # = TP1 (mục tiêu gần, chốt phần đầu)
    rr: float               # tỉ lệ Reward:Risk của TP1
    reason: str
    tp2: Optional[float] = None    # mục tiêu xa hơn (chốt phần còn lại)
    rr2: Optional[float] = None    # R:R của TP2
    tp_source: str = "swing"       # nguồn TP: 'liquidity' hay 'swing'

def _gather_tp_targets(direction: str, last: float, mtf, min_dist: float):
    """
    Gom các mục tiêu TP ở phía đối diện, ƯU TIÊN vùng liquidity (đỉnh/đáy bằng
    nhau — nơi giá 'thích' chạy tới) hơn swing đơn lẻ, và LỌC bỏ mục tiêu quá
    gần (nhỏ hơn min_dist — tránh TP vụn làm R:R thấp).

    Trả về (targets_sorted, source) — targets đã sắp theo thứ tự gần → xa.
    """
    liq, sw = [], []
    if direction == "LONG":
        liq = [q.level for q in mtf.ltf.liquidity if q.side == "buyside" and q.level > last]
        sw = [s.price for s in mtf.ltf.swings if s.kind == "high" and s.price > last]
    else:
        liq = [q.level for q in mtf.ltf.liquidity if q.side == "sellside" and q.level < last]
        sw = [s.price for s in mtf.ltf.swings if s.kind == "low" and s.price < last]

    # lọc mục tiêu quá gần (swing/vùng vụn) và giá không hợp lệ
    liq = [x for x in liq if abs(x - last) >= min_dist and x > 0]
    sw = [x for x in sw if abs(x - last) >= min_dist and x > 0]

    # ưu tiên liquidity; nếu không có thì dùng swing
    if liq:
        targets, source = liq, "liquidity"
    else:
        targets, source = sw, "swing"
    targets = sorted(set(targets), reverse=(direction == "SHORT"))   # gần -> xa
    return targets, source


def _best_ob(obs: list[OrderBlock], last_price: float, direction: str) -> Optional[OrderBlock]:
    """Chọn OB phù hợp nhất: gần giá hiện tại nhất, đúng phía chờ giá quay về."""
    if direction == "LONG":
        cand = [o for o in obs if o.top < last_price]      # OB nằm dưới giá -> chờ giá hồi xuống
    else:
        cand = [o for o in obs if o.bottom > last_price]   # OB nằm trên giá
    if not cand:
        return None
    # gần giá nhất = khoảng cách tới giá nhỏ nhất
    return min(cand, key=lambda o: abs((o.top + o.bottom) / 2 - last_price))

def build_plan(mtf: MTFResult, sl_buffer: float = 0.003,
               max_entry_distance: float = 0.05,
               require_sweep: bool = False,
               sweep_lookback: int = 15,
               min_rr: float = 0.0) -> Optional[Plan]:
    """
    Dựng kế hoạch vào lệnh từ kết quả multi-timeframe.

    Ưu tiên dùng OB hợp lưu (khung nhỏ trong vùng khung lớn). Nếu không có thì
    lùi về OB khung nhỏ thường. SL đặt ngoài OB 1 chút, TP tới swing đối diện
    gần nhất (mục tiêu thanh khoản). Tính sẵn R:R.

    max_entry_distance: vùng vào phải nằm trong khoảng này so với giá hiện tại.
    require_sweep : nếu True, CHỈ vào khi gần đây (trong sweep_lookback nến) có
                    cú quét thanh khoản CÙNG CHIỀU bias — bộ lọc chất lượng cao
                    (tay to quét stoploss xong mới đảo, theo lý thuyết SMC).
    """
    if mtf.bias == "neutral":
        return None
    direction = "LONG" if mtf.bias == "bull" else "SHORT"
    last = float(mtf.ltf_df["close"].iloc[-1])
    n = len(mtf.ltf_df)

    # bộ lọc cú quét liquidity gần đây cùng chiều bias
    if require_sweep:
        want_dir = "up" if direction == "LONG" else "down"
        recent_sweep = any(s.direction == want_dir and s.idx >= n - sweep_lookback
                           for s in mtf.ltf.sweeps)
        if not recent_sweep:
            return None

    # 1) ưu tiên OB hợp lưu
    conf = ltf_entries_in_htf_zone(mtf, tolerance=0.004)
    pool = [o for o in conf if not o.mitigated]
    src = "hợp lưu HTF+LTF"
    # 2) lùi về OB khung nhỏ còn tươi nếu không có hợp lưu
    if not pool:
        want = "up" if direction == "LONG" else "down"
        pool = [o for o in mtf.ltf.order_blocks if o.direction == want and not o.mitigated]
        src = "Order Block khung nhỏ"
    if not pool:
        return None

    ob = _best_ob(pool, last, direction)
    if ob is None:
        return None

    # KIỂM TRA: vùng vào có đủ gần giá hiện tại để thực sự vào được không?
    entry_mid = (ob.top + ob.bottom) / 2
    if abs(entry_mid - last) / last > max_entry_distance:
        return None                              # giá đã đi xa vùng vào -> không chase

    # SL trước (để biết 'risk', dùng làm chuẩn lọc mục tiêu quá gần)
    if direction == "LONG":
        sl = ob.bottom * (1 - sl_buffer)
        risk = entry_mid - sl
    else:
        sl = ob.top * (1 + sl_buffer)
        risk = sl - entry_mid
    if risk <= 0:
        return None

    # lọc mục tiêu quá gần: ít nhất bằng khoảng risk (để TP1 không vụn) hoặc 1 ATR
    atr_now = float(_atr(mtf.ltf_df)[-1])
    min_dist = max(risk, atr_now)
    targets, tp_source = _gather_tp_targets(direction, last, mtf, min_dist)

    if targets:
        tp1 = targets[0]                              # mục tiêu gần nhất (đã lọc)
        tp2 = targets[1] if len(targets) > 1 else None  # mục tiêu xa hơn (chốt phần 2)
    else:
        # dự phòng: không có mục tiêu cấu trúc -> dùng mức cố định
        tp1 = last * (1.04 if direction == "LONG" else 0.96)
        tp2 = None
        tp_source = "mặc định 4%"

    def _rr(tp):
        reward = (tp - entry_mid) if direction == "LONG" else (entry_mid - tp)
        return round(reward / risk, 2) if risk > 0 else 0.0

    rr = _rr(tp1)
    rr2 = _rr(tp2) if tp2 is not None else None

    if rr < min_rr:                              # bỏ kèo chất lượng kém (R:R thấp)
        return None
    return Plan(direction=direction,
                entry_top=ob.top, entry_bottom=ob.bottom,
                stoploss=sl, takeprofit=tp1, rr=rr, tp2=tp2, rr2=rr2,
                tp_source=tp_source,
                reason=f"Vào theo {src}, thuận bias {mtf.bias.upper()} của khung lớn.")


# ===========================================================================
# 3) NHẬN ĐỊNH TỔNG HỢP
# ===========================================================================
@dataclass
class Decision:
    bias: str
    aligned: bool
    in_range: bool
    range_zone: Optional[Range]
    plan: Optional[Plan]
    last_price: float
    htf_note: str

    def summary(self) -> str:
        """Xuất nhận định dạng văn bản tiếng Việt — dùng in ra hoặc hiển thị UI."""
        L = []
        bias_vn = {"bull": "TĂNG ▲", "bear": "GIẢM ▼", "neutral": "TRUNG LẬP ◆"}[self.bias]
        L.append(f"📊 Bias (khung lớn): {bias_vn}")
        L.append(f"   {self.htf_note}")
        L.append(f"💵 Giá hiện tại: {self.last_price:.2f}")

        if self.in_range and self.range_zone:
            r = self.range_zone
            L.append(f"⚠️  ĐANG GIẰNG CO trong vùng {r.bottom:.2f} – {r.top:.2f}.")
            L.append("   → Nên đứng ngoài, chờ giá phá vùng rồi mới hành động.")

        if self.plan:
            p = self.plan
            L.append(f"\n🎯 Setup gợi ý: {p.direction}")
            L.append(f"   Vùng vào : {p.entry_bottom:.2f} – {p.entry_top:.2f}")
            L.append(f"   Stoploss : {p.stoploss:.2f}")
            L.append(f"   Take profit: {p.takeprofit:.2f}")
            L.append(f"   R:R      : {p.rr}")
            L.append(f"   Lý do    : {p.reason}")
            if p.rr < 1.5:
                L.append("   ⚠️ R:R thấp (<1.5) — cân nhắc bỏ qua hoặc dời TP.")
            elif p.rr > 10:
                L.append("   ⚠️ R:R rất cao — do stoploss sát; dễ bị quét bởi nhiễu. "
                         "Cần backtest để biết tỉ lệ thắng thật.")
        else:
            L.append("\n🚫 Chưa có setup hợp lệ — đứng ngoài quan sát.")

        L.append("\n— Đây là công cụ tham khảo, KHÔNG phải lời khuyên đầu tư. —")
        return "\n".join(L)


def decide(df: pd.DataFrame, htf_rule: str = "4h", lookback: int = 2,
           min_atr_mult: float = 1.0, require_sweep: bool = False,
           min_rr: float = 0.0) -> Decision:
    """
    HÀM CHÍNH của Phần 4. Nhận DataFrame nến khung nhỏ -> trả Decision đầy đủ.

        df = get_candles('crypto', 'BTC/USDT', '1h')
        d  = decide(df, htf_rule='4h')
        print(d.summary())

    require_sweep: bật bộ lọc chất lượng — chỉ vào khi có cú quét liquidity gần đây.
    min_rr       : bỏ qua kèo có R:R thấp hơn ngưỡng này (lọc kèo kém).
    """
    mtf = analyze_mtf(df, htf_rule=htf_rule, lookback=lookback, min_atr_mult=min_atr_mult)
    rng = detect_range(df)
    plan = build_plan(mtf, require_sweep=require_sweep, min_rr=min_rr)

    # nếu đang giằng co thì huỷ kế hoạch (ưu tiên an toàn)
    if rng is not None:
        plan = None

    return Decision(bias=mtf.bias, aligned=mtf.aligned,
                    in_range=rng is not None, range_zone=rng,
                    plan=plan, last_price=float(df["close"].iloc[-1]),
                    htf_note=mtf.note)


if __name__ == "__main__":
    # Chạy thử: python -m smc.decision
    from smc.data import make_synthetic
    for seed in [11, 42, 5, 21]:
        df = make_synthetic(220, seed=seed)
        d = decide(df, htf_rule="4h")
        print("=" * 56)
        print(f"SEED {seed}")
        print(d.summary())
