"""
smc/backtest.py — BACKTEST (Phần 5)
====================================
Bước quan trọng nhất: KIỂM CHỨNG logic trên dữ liệu lịch sử trước khi tin nó
với tiền thật. Không có backtest = đánh bạc mù.

Cách hoạt động (walk-forward, không nhìn trộm tương lai):
    Tại mỗi nến i:
      1) Nếu đang RẢNH       -> chạy decide() trên dữ liệu TỚI i. Có kế hoạch
                                thì đặt lệnh chờ (pending) tại vùng vào.
      2) Nếu đang CHỜ KHỚP   -> nến sau chạm vùng vào thì khớp lệnh (filled).
                                Quá hạn chờ -> huỷ.
      3) Nếu đang CÓ LỆNH    -> nến sau chạm SL -> thua; chạm TP -> thắng.
                                (cùng 1 nến chạm cả hai -> tính THUA cho thận trọng)

Quy ước rủi ro: mỗi lệnh rủi ro 1 đơn vị (1R). Thắng = +R:R (theo kế hoạch),
thua = -1R. Tổng R cho biết hiệu quả không phụ thuộc số vốn.

LƯU Ý TRUNG THỰC: backtest đẹp KHÔNG đảm bảo tương lai. Nó chỉ loại bỏ những
logic dở rõ ràng. Cẩn thận với overfitting (chỉnh tham số cho khớp quá khứ).
"""

from __future__ import annotations
from dataclasses import dataclass, field
import pandas as pd

from smc.decision import decide


@dataclass
class Trade:
    direction: str
    entry: float
    sl: float
    tp: float
    rr: float
    open_idx: int
    close_idx: int = -1
    result: str = ""        # 'win' / 'loss'
    r_realized: float = 0.0 # +rr nếu thắng, -1 nếu thua


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)  # tổng R tích luỹ

    # ---- các chỉ số tổng hợp ----
    @property
    def n(self): return len(self.trades)
    @property
    def wins(self): return sum(1 for t in self.trades if t.result == "win")
    @property
    def losses(self): return sum(1 for t in self.trades if t.result == "loss")
    @property
    def win_rate(self): return self.wins / self.n if self.n else 0.0
    @property
    def total_r(self): return sum(t.r_realized for t in self.trades)
    @property
    def profit_factor(self):
        gain = sum(t.r_realized for t in self.trades if t.r_realized > 0)
        loss = -sum(t.r_realized for t in self.trades if t.r_realized < 0)
        return gain / loss if loss > 0 else float("inf")
    @property
    def max_drawdown(self):
        peak, mdd = 0.0, 0.0
        for eq in self.equity_curve:
            peak = max(peak, eq)
            mdd = min(mdd, eq - peak)
        return mdd
    @property
    def max_consec_loss(self):
        cur = best = 0
        for t in self.trades:
            cur = cur + 1 if t.result == "loss" else 0
            best = max(best, cur)
        return best

    def summary(self) -> str:
        if self.n == 0:
            return "Không có lệnh nào được kích hoạt trong giai đoạn này."
        L = [
            f"Số lệnh        : {self.n}",
            f"Thắng / Thua   : {self.wins} / {self.losses}",
            f"Tỉ lệ thắng    : {self.win_rate*100:.1f}%",
            f"Tổng R         : {self.total_r:+.2f}R",
            f"Profit factor  : {self.profit_factor:.2f}",
            f"Max drawdown   : {self.max_drawdown:.2f}R",
            f"Chuỗi thua dài : {self.max_consec_loss}",
        ]
        return "\n".join(L)


def run_backtest(df: pd.DataFrame,
                 htf_rule: str = "4h",
                 warmup: int = 120,
                 window: int = 200,
                 max_wait: int = 20,
                 step: int = 1,
                 fee_pct: float = 0.0004,
                 slippage_pct: float = 0.0005,
                 require_sweep: bool = False,
                 min_rr: float = 0.0) -> BacktestResult:
    """
    Chạy backtest walk-forward.

        df       : nến khung nhỏ (lịch sử dài, vd lấy bằng fetch_crypto_history)
        htf_rule : khung lớn cho multi-timeframe
        warmup   : số nến đầu bỏ qua (cần đủ dữ liệu để phân tích)
        window   : chỉ phân tích `window` nến gần nhất mỗi lần (giới hạn chi phí
                   tính toán; tránh O(n^2) trên dữ liệu rất dài)
        max_wait : lệnh chờ quá số nến này chưa khớp -> huỷ
        step     : chỉ quét tìm kèo mỗi `step` nến (tăng để chạy nhanh hơn)
        fee_pct  : phí MỖI CHIỀU theo % giá trị lệnh (vd 0.0004 = 0.04%, taker crypto).
                   Áp 2 lần (vào + ra).
        slippage_pct : trượt giá MỖI CHIỀU theo % giá (khớp lệnh xấu hơn kỳ vọng).
                   Áp 2 lần (vào + ra).

    Phí & trượt giá được quy về "R" rồi TRỪ vào kết quả mỗi lệnh, nên backtest
    sát thực tế hơn (lệnh thật luôn tốn chi phí, kết quả thật kém hơn lý thuyết).

    Trả về BacktestResult với đầy đủ chỉ số.
    """
    res = BacktestResult()
    equity = 0.0
    n = len(df)

    high = df["high"].values
    low = df["low"].values

    i = warmup
    while i < n:
        # chỉ tìm kèo mới khi đang rảnh
        start = max(0, i - window)
        sub = df.iloc[start:i + 1]
        d = decide(sub, htf_rule=htf_rule, require_sweep=require_sweep, min_rr=min_rr)

        if d.plan is None:
            i += step
            continue

        p = d.plan
        # ---- giai đoạn CHỜ KHỚP ----
        filled_at = -1
        for j in range(i + 1, min(i + 1 + max_wait, n)):
            # giá chạm vùng vào?
            if low[j] <= p.entry_top and high[j] >= p.entry_bottom:
                filled_at = j
                break
        if filled_at == -1:
            i += step
            continue

        # ---- giai đoạn CÓ LỆNH: SL trước hay TP trước? ----
        entry_price = (p.entry_top + p.entry_bottom) / 2
        result, close_idx, r = "", -1, 0.0
        for k in range(filled_at, n):
            hit_sl = low[k] <= p.stoploss if p.direction == "LONG" else high[k] >= p.stoploss
            hit_tp = high[k] >= p.takeprofit if p.direction == "LONG" else low[k] <= p.takeprofit
            if hit_sl and hit_tp:
                result, r = "loss", -1.0          # cùng nến -> tính thua (thận trọng)
                close_idx = k; break
            if hit_sl:
                result, r = "loss", -1.0; close_idx = k; break
            if hit_tp:
                result, r = "win", p.rr; close_idx = k; break

        if result == "":                          # chưa đóng tới cuối dữ liệu -> bỏ
            break

        # ---- trừ phí + trượt giá (quy về R) ----
        # rủi ro 1R tính bằng khoảng cách giá entry -> SL
        risk_price = abs(entry_price - p.stoploss)
        if risk_price > 0:
            # chi phí giá: phí 2 chiều + trượt giá 2 chiều, tính trên giá entry
            cost_price = entry_price * (2 * fee_pct + 2 * slippage_pct)
            cost_r = cost_price / risk_price
        else:
            cost_r = 0.0
        r_net = r - cost_r                          # cả thắng lẫn thua đều chịu chi phí

        t = Trade(direction=p.direction, entry=entry_price, sl=p.stoploss,
                  tp=p.takeprofit, rr=p.rr, open_idx=filled_at,
                  close_idx=close_idx, result=result, r_realized=r_net)
        res.trades.append(t)
        equity += r_net
        res.equity_curve.append(equity)

        # nhảy tới sau khi lệnh đóng (1 lệnh tại 1 thời điểm)
        i = max(close_idx + 1, i + step)

    return res


# ===========================================================================
# KIỂM TRA ĐỘ ỔN ĐỊNH — chạy backtest trên nhiều giai đoạn
# ===========================================================================
@dataclass
class StabilityResult:
    segments: list           # list[(tên, BacktestResult)]
    @property
    def total_rs(self):
        return [bt.total_r for _, bt in self.segments if bt.n > 0]
    def summary(self) -> str:
        rs = self.total_rs
        if not rs:
            return "Không giai đoạn nào có lệnh."
        import statistics as stt
        n_pos = sum(1 for r in rs if r > 0)
        mean = stt.mean(rs)
        sd = stt.pstdev(rs) if len(rs) > 1 else 0.0
        L = [
            f"Số giai đoạn có lệnh : {len(rs)}",
            f"Giai đoạn LỜI        : {n_pos}/{len(rs)}",
            f"Tổng R trung bình    : {mean:+.2f}R",
            f"Độ dao động (lệch)   : {sd:.2f}R",
        ]
        # đánh giá tự động
        if mean > 0 and mean > sd:
            L.append("→ Có dấu hiệu LỢI THẾ: lời trung bình lớn hơn độ dao động.")
        elif mean > 0:
            L.append("→ Lời trung bình DƯƠNG nhưng dao động lớn — chưa chắc chắn.")
        else:
            L.append("→ CHƯA có lợi thế: trung bình quanh 0 hoặc âm.")
        return "\n".join(L)


def run_stability(df: pd.DataFrame, n_segments: int = 4, **bt_kwargs) -> StabilityResult:
    """
    Chia dữ liệu thành `n_segments` đoạn LIÊN TIẾP và backtest từng đoạn.

    Mục đích: một logic có lợi thế thật phải LỜI ỔN ĐỊNH qua nhiều giai đoạn,
    không phải chỉ đẹp ở 1 đoạn rồi loạn ở đoạn khác. Nếu kết quả nhảy lung tung
    (lúc +, lúc −) thì đó là dấu hiệu chưa có edge, chỉ là may rủi.
    """
    seg_len = len(df) // n_segments
    out = []
    for s in range(n_segments):
        lo = s * seg_len
        hi = len(df) if s == n_segments - 1 else (s + 1) * seg_len
        seg = df.iloc[lo:hi]
        if len(seg) < 160:                          # quá ngắn -> bỏ
            continue
        t0 = seg.index[0].strftime("%Y-%m-%d")
        t1 = seg.index[-1].strftime("%Y-%m-%d")
        bt = run_backtest(seg, warmup=min(120, len(seg) // 3), **bt_kwargs)
        out.append((f"{t0} → {t1}", bt))
    return StabilityResult(segments=out)
    # Chạy thử: python -m smc.backtest
    from smc.data import make_synthetic
    df = make_synthetic(2000, seed=7)
    print(f"Backtest trên {len(df)} nến giả...\n")
    res = run_backtest(df, htf_rule="4h", warmup=150, window=200)
    print(res.summary())

    if res.n:
        print("\n5 lệnh gần nhất:")
        for t in res.trades[-5:]:
            print(f"  {t.direction:5} entry {t.entry:7.2f} | {t.result:4} | {t.r_realized:+.2f}R")
