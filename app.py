"""
app.py — GIAO DIỆN (Phần 7)
============================
Ghép tất cả lại thành app Streamlit dùng được:

    - chọn thị trường / mã / khung thời gian ở sidebar
    - biểu đồ nến (Plotly) có vẽ: swing, BOS/CHoCH, FVG, Order Block, range
    - bảng NHẬN ĐỊNH SMC (bias, vùng vào, SL/TP, R:R) + WYCKOFF
    - nút chạy BACKTEST hiện win rate, tổng R, đường vốn

Chạy:   streamlit run app.py
(Chưa cài data lib hoặc không có mạng -> chọn "Dữ liệu mô phỏng" ở sidebar.)
"""

from __future__ import annotations
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from smc.data import make_synthetic, get_candles
from smc.engine import analyze
from smc.decision import decide
from smc.wyckoff import analyze_wyckoff
from smc.backtest import run_backtest, run_stability
from smc import ai as smc_ai
from smc.confluence import score_confluence, rsi, _is_bullish_reversal, _is_bearish_reversal
from smc.scanner import scan_one, rank
from smc.catalog import CATALOG as FULL_CATALOG
import os as _os
if _os.environ.get("DATABASE_URL"):     # có Supabase -> dùng cloud (chung với GitHub Actions)
    from smc import db as wl
else:                                    # không -> dùng SQLite local
    from smc import watchlist as wl


def fmt_price(p) -> str:
    """Hiển thị giá với số chữ số thập phân thích nghi theo độ lớn.
    Tránh lỗi 'làm tròn về 0' với coin giá siêu nhỏ (PEPE, SHIB...)."""
    try:
        a = abs(float(p))
    except (TypeError, ValueError):
        return str(p)
    if a >= 1000:   return f"{p:,.2f}"
    if a >= 1:      return f"{p:.2f}"
    if a >= 0.01:   return f"{p:.4f}"
    if a >= 0.0001: return f"{p:.6f}"
    if a > 0:       return f"{p:.10f}".rstrip("0")
    return "0"


# ---------------------------------------------------------------------------
# Vẽ biểu đồ nến + overlay SMC
# ---------------------------------------------------------------------------
def build_chart(df, res, decision, wyckoff, show, view_bars=120):
    """Dựng figure Plotly. `show` là dict bật/tắt overlay.
    view_bars: chỉ PHÓNG vào số nến gần nhất này (nến to, dễ đọc) — dữ liệu cũ
    vẫn còn, kéo/zoom ra xem được."""
    t = df.index
    # 3 tầng: giá (trên, lớn nhất) + volume (giữa) + RSI (dưới)
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True,
                        row_heights=[0.66, 0.15, 0.19], vertical_spacing=0.02)

    # nến (tầng giá)
    fig.add_trace(go.Candlestick(
        x=t, open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="Giá", increasing_line_color="#26c281", decreasing_line_color="#ed5565",
        increasing_fillcolor="#26c281", decreasing_fillcolor="#ed5565"),
        row=1, col=1)

    # volume (tầng dưới) — xanh nếu nến tăng, đỏ nếu giảm
    vol_col = ["#26c281" if c >= o else "#ed5565"
               for o, c in zip(df["open"], df["close"])]
    fig.add_trace(go.Bar(x=t, y=df["volume"], marker_color=vol_col,
                         name="Volume", showlegend=False, opacity=0.6),
                  row=2, col=1)

    def xf(i):   # index nến -> mốc thời gian
        return t[i]

    # ----- Order Block — chỉ vùng còn hiệu lực, gần nhất -----
    if show["ob"]:
        live_ob = [o for o in res.order_blocks if not o.mitigated][-6:]
        for ob in live_ob:
            col = "rgba(38,194,129,0.18)" if ob.direction == "up" else "rgba(237,85,101,0.18)"
            line = "#26c281" if ob.direction == "up" else "#ed5565"
            fig.add_shape(type="rect", x0=xf(ob.idx), x1=t[-1],
                          y0=ob.bottom, y1=ob.top, fillcolor=col,
                          line=dict(color=line, width=1), layer="below", row=1, col=1)

    # ----- FVG — vài cái còn mở gần nhất -----
    if show["fvg"]:
        live_fvg = [g for g in res.fvgs if not g.mitigated][-6:]
        for g in live_fvg:
            fig.add_shape(type="rect", x0=xf(g.idx), x1=t[-1],
                          y0=g.bottom, y1=g.top, fillcolor="rgba(58,143,255,0.22)",
                          line=dict(color="#3a8fff", width=1, dash="dot"),
                          layer="below", row=1, col=1)
            fig.add_annotation(x=xf(g.idx), y=(g.top + g.bottom) / 2, text="FVG",
                               showarrow=False, font=dict(color="#9ec3ff", size=9),
                               xanchor="left", row=1, col=1)

    # ----- Range Wyckoff -----
    if show["range"] and wyckoff.trading_range:
        r = wyckoff.trading_range
        fig.add_shape(type="rect", x0=xf(r.start), x1=t[-1],
                      y0=r.bottom, y1=r.top, fillcolor="rgba(245,166,35,0.07)",
                      line=dict(color="#f5a623", width=1, dash="dot"),
                      layer="below", row=1, col=1)

    # ----- Swing (điểm) -----
    if show["swings"]:
        hi = [s for s in res.swings if s.kind == "high"]
        lo = [s for s in res.swings if s.kind == "low"]
        fig.add_trace(go.Scatter(x=[xf(s.idx) for s in hi], y=[s.price for s in hi],
                                 mode="markers", name="Swing High",
                                 marker=dict(color="#ed5565", size=10, symbol="triangle-down",
                                             line=dict(color="#ffffff", width=1))),
                      row=1, col=1)
        fig.add_trace(go.Scatter(x=[xf(s.idx) for s in lo], y=[s.price for s in lo],
                                 mode="markers", name="Swing Low",
                                 marker=dict(color="#26c281", size=10, symbol="triangle-up",
                                             line=dict(color="#ffffff", width=1))),
                      row=1, col=1)

    # ----- BOS / CHoCH — chỉ ghi nhãn cho CHoCH -----
    if show["structure"]:
        for e in res.events:
            is_ch = e.kind == "CHoCH"
            col = "#f5a623" if is_ch else "#8b5cf6"
            x0 = xf(max(0, e.idx - 5))
            fig.add_shape(type="line", x0=x0, x1=xf(e.idx), y0=e.level, y1=e.level,
                          line=dict(color=col, width=1.2 if is_ch else 0.8,
                                    dash="dash" if is_ch else "dot"), row=1, col=1)
            if is_ch:
                fig.add_annotation(x=xf(e.idx), y=e.level, text="CHoCH",
                                   showarrow=False, font=dict(color="#f5a623", size=11),
                                   xanchor="left", yshift=10, row=1, col=1)
            else:
                fig.add_annotation(x=xf(e.idx), y=e.level, text="BOS",
                                   showarrow=False, font=dict(color="#a78bfa", size=9),
                                   xanchor="left", yshift=8, row=1, col=1)

    # ----- Wyckoff spring / upthrust + climax -----
    if show["wyckoff"]:
        sp = [s for s in wyckoff.signals if s.kind == "spring"]
        up = [s for s in wyckoff.signals if s.kind == "upthrust"]
        if sp:
            # đã xác nhận (có test) viền vàng to hơn; chưa thì thường
            fig.add_trace(go.Scatter(
                x=[xf(s.idx) for s in sp], y=[s.price for s in sp],
                mode="markers", name="Spring",
                marker=dict(color="#26c281",
                            size=[18 if s.confirmed else 13 for s in sp],
                            symbol="star",
                            line=dict(color=["#ffd166" if s.confirmed else "#ffffff" for s in sp],
                                      width=[2.5 if s.confirmed else 1 for s in sp]))),
                row=1, col=1)
        if up:
            fig.add_trace(go.Scatter(
                x=[xf(s.idx) for s in up], y=[s.price for s in up],
                mode="markers", name="Upthrust",
                marker=dict(color="#ed5565",
                            size=[18 if s.confirmed else 13 for s in up],
                            symbol="star",
                            line=dict(color=["#ffd166" if s.confirmed else "#ffffff" for s in up],
                                      width=[2.5 if s.confirmed else 1 for s in up]))),
                row=1, col=1)
        # climax (SC/BC) — tam giác lớn
        sc = [c for c in wyckoff.climaxes if c.kind == "sc"]
        bc = [c for c in wyckoff.climaxes if c.kind == "bc"]
        if sc:
            fig.add_trace(go.Scatter(x=[xf(c.idx) for c in sc], y=[c.price for c in sc],
                                     mode="markers+text", name="Selling Climax",
                                     text=["SC"] * len(sc), textposition="bottom center",
                                     textfont=dict(color="#26c281", size=11),
                                     marker=dict(color="#26c281", size=16, symbol="triangle-up",
                                                 line=dict(color="#ffd166", width=1.5))),
                          row=1, col=1)
        if bc:
            fig.add_trace(go.Scatter(x=[xf(c.idx) for c in bc], y=[c.price for c in bc],
                                     mode="markers+text", name="Buying Climax",
                                     text=["BC"] * len(bc), textposition="top center",
                                     textfont=dict(color="#ed5565", size=11),
                                     marker=dict(color="#ed5565", size=16, symbol="triangle-down",
                                                 line=dict(color="#ffd166", width=1.5))),
                          row=1, col=1)
        # nến hấp thụ — chấm tròn nhỏ ở đáy nến
        if wyckoff.absorption:
            fig.add_trace(go.Scatter(
                x=[xf(i) for i in wyckoff.absorption],
                y=[df["low"].iloc[i] * 0.997 for i in wyckoff.absorption],
                mode="markers", name="Hấp thụ (effort>result)",
                marker=dict(color="#c77dff", size=7, symbol="circle")), row=1, col=1)

    # ----- Liquidity (đường ngang) + Sweep (dấu) -----
    if show.get("liquidity"):
        for lq in res.liquidity[-8:]:
            # đã bị quét -> mờ; chưa quét -> rõ (vùng còn "mồi")
            swept = lq.swept_at >= 0
            col = "#6b7785" if swept else ("#ed5565" if lq.side == "buyside" else "#26c281")
            x0 = xf(min(lq.idxs))
            fig.add_shape(type="line", x0=x0, x1=t[-1], y0=lq.level, y1=lq.level,
                          line=dict(color=col, width=1, dash="dot"),
                          opacity=0.5 if swept else 0.9, row=1, col=1)
            if not swept:
                fig.add_annotation(x=t[-1], y=lq.level, text="LQ",
                                   showarrow=False, font=dict(color=col, size=8),
                                   xanchor="right", row=1, col=1)
        # dấu cú quét
        sw_up = [s for s in res.sweeps if s.direction == "up"]
        sw_dn = [s for s in res.sweeps if s.direction == "down"]
        if sw_up:
            fig.add_trace(go.Scatter(x=[xf(s.idx) for s in sw_up], y=[s.level for s in sw_up],
                                     mode="markers", name="Quét đáy (bullish)",
                                     marker=dict(color="#26c281", size=11, symbol="x-thin",
                                                 line=dict(color="#26c281", width=2))),
                          row=1, col=1)
        if sw_dn:
            fig.add_trace(go.Scatter(x=[xf(s.idx) for s in sw_dn], y=[s.level for s in sw_dn],
                                     mode="markers", name="Quét đỉnh (bearish)",
                                     marker=dict(color="#ed5565", size=11, symbol="x-thin",
                                                 line=dict(color="#ed5565", width=2))),
                          row=1, col=1)

    # ----- Nến đảo chiều (pin bar / engulfing) -----
    if show.get("reversal"):
        bull_idx = [i for i in range(1, len(df)) if _is_bullish_reversal(df, i)]
        bear_idx = [i for i in range(1, len(df)) if _is_bearish_reversal(df, i)]
        if bull_idx:
            fig.add_trace(go.Scatter(
                x=[t[i] for i in bull_idx],
                y=[df["low"].iloc[i] * 0.999 for i in bull_idx],
                mode="markers", name="Nến đảo tăng",
                marker=dict(color="#26c281", size=9, symbol="diamond",
                            line=dict(color="#ffffff", width=0.5))), row=1, col=1)
        if bear_idx:
            fig.add_trace(go.Scatter(
                x=[t[i] for i in bear_idx],
                y=[df["high"].iloc[i] * 1.001 for i in bear_idx],
                mode="markers", name="Nến đảo giảm",
                marker=dict(color="#ed5565", size=9, symbol="diamond",
                            line=dict(color="#ffffff", width=0.5))), row=1, col=1)

    # ----- RSI (tầng 3) -----
    if show.get("rsi"):
        r = rsi(df["close"])
        fig.add_trace(go.Scatter(x=t, y=r, mode="lines", name="RSI",
                                 line=dict(color="#c77dff", width=1.4),
                                 showlegend=False), row=3, col=1)
        # vạch quá mua 70 / quá bán 30
        fig.add_hline(y=70, line=dict(color="#ed5565", width=0.8, dash="dot"), row=3, col=1)
        fig.add_hline(y=30, line=dict(color="#26c281", width=0.8, dash="dot"), row=3, col=1)
        fig.add_hline(y=50, line=dict(color="#2a3744", width=0.6), row=3, col=1)

    # ----- Kế hoạch: Entry / SL / TP / R:R (chỉ hiện khi có lệnh hợp lệ) -----
    if show["plan"] and decision.plan:
        p = decision.plan
        x_entry = t[max(0, len(t) - 30)]
        # vùng vào lệnh
        fig.add_shape(type="rect", x0=x_entry, x1=t[-1],
                      y0=p.entry_bottom, y1=p.entry_top,
                      fillcolor="rgba(245,166,35,0.18)", line=dict(color="#f5a623", width=1),
                      row=1, col=1)
        fig.add_annotation(x=x_entry, y=p.entry_top,
                           text=f"ENTRY {p.direction} · R:R {p.rr}",
                           showarrow=False, font=dict(color="#f5a623", size=12),
                           xanchor="left", yshift=10, row=1, col=1)
        # cắt lỗ
        fig.add_hline(y=p.stoploss, line=dict(color="#ed5565", width=1.2, dash="dot"),
                      annotation_text=f"SL  {fmt_price(p.stoploss)}", annotation_position="right",
                      annotation_font=dict(color="#ed5565", size=12), row=1, col=1)
        # chốt lời 1
        fig.add_hline(y=p.takeprofit, line=dict(color="#26c281", width=1.2, dash="dot"),
                      annotation_text=f"TP1  {fmt_price(p.takeprofit)}", annotation_position="right",
                      annotation_font=dict(color="#26c281", size=12), row=1, col=1)
        # chốt lời 2 (xa hơn) nếu có
        if p.tp2 is not None:
            fig.add_hline(y=p.tp2, line=dict(color="#1b8a5a", width=1, dash="dashdot"),
                          annotation_text=f"TP2  {fmt_price(p.tp2)}", annotation_position="right",
                          annotation_font=dict(color="#1b8a5a", size=11), row=1, col=1)

    # Phóng vào `view_bars` nến gần nhất.
    vb = min(view_bars, len(df))
    seg = df.iloc[-vb:]
    pad = (seg["high"].max() - seg["low"].min()) * 0.08
    y0 = float(seg["low"].min() - pad)
    y1 = float(seg["high"].max() + pad)

    fig.update_layout(
        template="plotly_dark", height=880, margin=dict(l=10, r=70, t=10, b=10),
        xaxis_rangeslider_visible=False, showlegend=True,
        legend=dict(orientation="h", y=1.06, x=0,
                    font=dict(color="#e8edf2", size=14),
                    bgcolor="rgba(20,28,38,0.85)", bordercolor="#2a3744", borderwidth=1,
                    itemsizing="constant"),
        paper_bgcolor="#0a0e14", plot_bgcolor="#0a0e14",
        dragmode="pan", bargap=0,
        hovermode="x unified")        # rê chuột -> hiện giá theo cột thời gian
    # đường gióng (crosshair) khi rê chuột
    fig.update_xaxes(showspikes=True, spikemode="across", spikethickness=1,
                     spikecolor="#5f7185", spikedash="dot")
    fig.update_yaxes(showspikes=True, spikethickness=1,
                     spikecolor="#5f7185", spikedash="dot", row=1, col=1)
    # khung nhìn: ép sát mép dữ liệu cho cả 2 tầng (trục x dùng chung)
    fig.update_xaxes(range=[t[-vb], t[-1]], autorange=False)
    fig.update_yaxes(range=[y0, y1], autorange=False, row=1, col=1,
                     nticks=12, gridcolor="#16202c", showgrid=True)
    fig.update_yaxes(title_text="Vol", row=2, col=1)
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=3, col=1)
    return fig


# ---------------------------------------------------------------------------
# Giao diện
# ---------------------------------------------------------------------------
def main():
    st.set_page_config(page_title="SMC + Wyckoff Analyzer", layout="wide")
    # làm sáng chữ caption + chú thích (mặc định Streamlit để xám nhạt, khó đọc nền tối)
    st.markdown("""
        <style>
        [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] *,
        .stCaption, small {
            color: #334155 !important;
            font-size: 13.5px !important;
            opacity: 1 !important;
        }
        .chart-legend, .chart-legend * { color: #1e293b !important; opacity: 1 !important; }
        </style>
    """, unsafe_allow_html=True)
    st.title("SMC + Wyckoff Analyzer")
    st.caption("Phân tích Smart Money Concepts & Wyckoff — công cụ tham khảo, KHÔNG phải lời khuyên đầu tư.")

    # ----- Sidebar -----
    sb = st.sidebar
    sb.header("Cấu hình")
    source = sb.radio("Nguồn dữ liệu", ["Dữ liệu thật", "Dữ liệu mô phỏng (thử/dự phòng)"], index=0)
    is_real = source == "Dữ liệu thật"

    if is_real:
        # nhóm tài sản -> danh sách chọn sẵn {tên hiển thị: (market, mã Yahoo/ccxt)}
        from smc.catalog import CATALOG
        group = sb.selectbox("Nhóm tài sản", list(CATALOG.keys()))
        choices = CATALOG[group]
        pick = sb.selectbox("Chọn tài sản", list(choices.keys()) + ["➕ Tự nhập mã khác"])
        if pick == "➕ Tự nhập mã khác":
            MARKET_VN = {"crypto": "Crypto", "forex": "Forex", "commodity": "Hàng hoá",
                         "stock": "Cổ phiếu Mỹ", "index": "Chỉ số", "vn": "Chứng khoán VN"}
            market = sb.selectbox("Thị trường", list(MARKET_VN),
                                  format_func=lambda x: MARKET_VN[x])
            symbol = sb.text_input("Mã (VN: VCB, FPT… | Yahoo: GC=F… | ccxt: BTC/USDT)", "VCB")
            sb.caption("VN: mã cổ phiếu/chỉ số (VCB, VNINDEX…). Quốc tế: tra trên "
                       "finance.yahoo.com. Crypto: định dạng BTC/USDT.")
        else:
            market, symbol = choices[pick]
        # crypto (ccxt) có 4h; Yahoo không có 4h -> chỉ 15m/1h/1d
        tf_opts = ["15m", "1h", "4h", "1d"] if market == "crypto" else ["15m", "1h", "1d"]
        timeframe = sb.selectbox("Khung nhỏ", tf_opts, index=1)
    else:
        group = None
        seed = sb.number_input("Seed (đổi để xem kịch bản khác)", 1, 9999, 7)
        n = sb.slider("Số nến", 150, 1000, 400, step=50)

    htf_rule = sb.selectbox("Khung lớn (bias)", ["4h", "1D", "1W"], index=0)
    lookback = sb.slider("Độ nhạy swing (lookback)", 1, 5, 3)
    min_atr = sb.slider("Lọc nhiễu (cao = sạch hơn)", 0.0, 3.0, 1.5, step=0.5,
                        help="Bỏ swing vụn nhỏ hơn mức này × ATR. Tăng lên nếu biểu đồ rối.")
    view_bars = sb.slider("Số nến hiển thị", 40, 300, 80, step=10,
                          help="Ít nến -> nến to/dày, dễ đọc. Nhiều nến -> nhìn toàn cảnh.")
    require_sweep = sb.checkbox("Chỉ vào khi có cú quét liquidity",
                                help="Bộ lọc chất lượng cao: chỉ vào lệnh khi gần đây có cú "
                                     "quét thanh khoản cùng chiều. Bật/tắt rồi backtest để so sánh.")
    min_rr = sb.slider("R:R tối thiểu", 0.0, 5.0, 0.0, step=0.5,
                       help="Bỏ qua kèo có R:R thấp hơn mức này. 0 = không lọc. "
                            "Tăng lên rồi backtest để xem có giúp ích không.")

    with sb.expander("⚙️ Độ nhạy Wyckoff"):
        st.caption("Giảm = nhạy hơn (bắt nhiều tín hiệu), tăng = chặt hơn (chỉ tín hiệu mạnh).")
        wy_window = st.slider("Độ dài range xét", 25, 80, 40, step=5,
                              help="Số nến tìm vùng đi ngang. Lớn -> range dài hơn.")
        wy_climax = st.slider("Ngưỡng volume Climax (×TB)", 1.5, 4.0, 2.5, step=0.1,
                              help="Volume gấp mấy lần trung bình thì coi là cao trào SC/BC.")
        wy_absorb = st.slider("Ngưỡng volume Hấp thụ (×TB)", 1.5, 4.0, 2.0, step=0.1,
                              help="Volume cao mà giá đi ít = hấp thụ.")
        wy_spike = st.slider("Ngưỡng volume Spring/Upthrust (×TB)", 1.0, 3.0, 1.5, step=0.1,
                             help="Volume gấp mấy lần thì coi cú quét là 'volume cao xác nhận'.")

    sb.header("AI (tuỳ chọn)")
    import os
    api_key = sb.text_input("Anthropic API key", type="password",
                            value=os.environ.get("ANTHROPIC_API_KEY", ""),
                            help="Lấy ở console.anthropic.com → API Keys. Bỏ trống nếu "
                                 "không dùng AI. Có thể đặt sẵn biến môi trường ANTHROPIC_API_KEY.").strip()

    sb.header("Hiển thị")
    show = {
        "swings":    sb.checkbox("Đỉnh/đáy (Swing)", True),
        "structure": sb.checkbox("Cấu trúc (BOS/CHoCH)", True),
        "fvg":       sb.checkbox("Khoảng mất cân bằng (FVG)", True),
        "ob":        sb.checkbox("Vùng tay to (Order Block)", True),
        "range":     sb.checkbox("Vùng đi ngang (Range)", True),
        "wyckoff":   sb.checkbox("Phá biên giả (Spring/Upthrust)", True),
        "liquidity": sb.checkbox("Thanh khoản (Liquidity/Sweep)", True),
        "rsi":       sb.checkbox("RSI (tầng dưới)", True),
        "reversal":  sb.checkbox("Nến đảo chiều (pin/engulfing)", False),
        "plan":      sb.checkbox("Vùng vào lệnh", True),
    }

    # ----- Lấy dữ liệu -----
    try:
        if is_real:
            df = get_candles(market, symbol, timeframe)
        else:
            df = make_synthetic(int(n), seed=int(seed))
            st.warning("⚠️ Đang dùng DỮ LIỆU MÔ PHỎNG (ngẫu nhiên) — tín hiệu chỉ để "
                       "thử giao diện/engine, KHÔNG có giá trị giao dịch thật.")
    except Exception as e:
        st.error(f"Không lấy được dữ liệu thật ({e}). Hãy thử mã khác, đổi khung "
                 f"thời gian, hoặc dùng 'Dữ liệu mô phỏng' để kiểm tra app.")
        return

    # ----- Phân tích -----
    res = analyze(df, lookback=lookback, min_atr_mult=min_atr)
    decision = decide(df, htf_rule=htf_rule, lookback=lookback, min_atr_mult=min_atr, require_sweep=require_sweep, min_rr=min_rr)
    wyckoff = analyze_wyckoff(df, window=wy_window,
                              climax_vol_mult=wy_climax, absorption_vol_mult=wy_absorb,
                              spike_mult=wy_spike)

    # ----- Chart full bề ngang -----
    st.plotly_chart(build_chart(df, res, decision, wyckoff, show, view_bars),
                    use_container_width=True,
                    config={
                        "scrollZoom": True,           # lăn chuột để zoom
                        "displayModeBar": True,       # luôn hiện thanh công cụ
                        "displaylogo": False,
                        "modeBarButtonsToAdd": ["pan2d", "hoverClosestCartesian",
                                                "hoverCompareCartesian"],
                    })
    st.markdown(
        '<div style="color:#334155;font-size:13.5px;margin:4px 0;font-weight:500">'
        '🖱️ Thanh công cụ góc phải trên chart: ✋ = kéo để di chuyển; 🔍 = kéo để zoom vùng; '
        'rê chuột lên nến để xem giá. Lăn chuột để phóng to/thu nhỏ.</div>',
        unsafe_allow_html=True)

    # ----- Chú thích màu (vì các vùng OB/FVG/range không hiện trong legend) -----
    def chip(color, label, border=None):
        b = f"border:1px solid {border};" if border else ""
        return (f'<span style="display:inline-block;width:13px;height:13px;'
                f'background:{color};{b}border-radius:3px;vertical-align:middle;'
                f'margin:0 5px 0 14px"></span>{label}')
    legend_html = (
        '<div class="chart-legend" style="font-size:14px;color:#1e293b;line-height:2.1;font-weight:500">'
        + chip("rgba(38,194,129,0.5)", "Vùng tay to tăng (Order Block)", "#26c281")
        + chip("rgba(237,85,101,0.5)", "Vùng tay to giảm (Order Block)", "#ed5565")
        + chip("rgba(58,143,255,0.5)", "Khoảng mất cân bằng (FVG)", "#3a8fff")
        + chip("rgba(245,166,35,0.25)", "Vùng đi ngang / Vùng vào lệnh", "#f5a623")
        + '<br>'
        + chip("#f5a623", "CHoCH — đảo cấu trúc")
        + chip("#8b5cf6", "BOS — phá cấu trúc (vạch chấm)")
        + chip("#26c281", "▲ Đáy (Swing Low) / ★ Spring")
        + chip("#ed5565", "▼ Đỉnh (Swing High) / ★ Upthrust")
        + '</div>')
    st.markdown(legend_html, unsafe_allow_html=True)
    st.divider()

    # ----- Bảng thao tác xuống dưới, xếp ngang 3 cột -----
    c_dec, c_wy, c_stat = st.columns(3)

    with c_dec:
        st.subheader("Nhận định")
        bias_vn = {"bull": "🟢 TĂNG", "bear": "🔴 GIẢM", "neutral": "🟡 TRUNG LẬP"}[decision.bias]
        st.markdown(f"### {bias_vn}")
        st.caption(decision.htf_note)
        if decision.in_range:
            st.warning("Đang giằng co — nên đứng ngoài.")
        if decision.plan:
            p = decision.plan
            st.markdown(f"**Lệnh gợi ý: {p.direction}**")
            tp2_line = (f"\nChốt lời 2  : {fmt_price(p.tp2)}  (R:R {p.rr2})"
                        if p.tp2 is not None else "")
            st.text(f"Vùng vào    : {fmt_price(p.entry_bottom)}–{fmt_price(p.entry_top)}\n"
                    f"Cắt lỗ (SL) : {fmt_price(p.stoploss)}\n"
                    f"Chốt lời 1  : {fmt_price(p.takeprofit)}  (R:R {p.rr})"
                    f"{tp2_line}\n"
                    f"Mục tiêu TP : {p.tp_source}")
        else:
            st.info("Chưa có lệnh hợp lệ — nên đứng ngoài.")

    with c_wy:
        st.subheader("Wyckoff")
        wy = {"accumulation": "🟢 Tích luỹ", "distribution": "🔴 Phân phối",
              "unclear": "🟡 Chưa rõ"}[wyckoff.bias_hint]
        st.markdown(f"### {wy}")
        st.caption(wyckoff.note)
        n_conf = sum(1 for s in wyckoff.signals if s.confirmed)
        if wyckoff.signals or wyckoff.climaxes:
            st.text(f"Spring/Upthrust : {len(wyckoff.signals)} "
                    f"(✓ test: {n_conf})\n"
                    f"Climax (SC/BC)  : {len(wyckoff.climaxes)}\n"
                    f"Nến hấp thụ     : {len(wyckoff.absorption)}")

    with c_stat:
        st.subheader("Thống kê")
        st.text(f"Đỉnh/đáy   : {sum(1 for s in res.swings if s.kind=='high')} đỉnh / "
                f"{sum(1 for s in res.swings if s.kind=='low')} đáy\n"
                f"BOS        : {sum(1 for e in res.events if e.kind=='BOS')}\n"
                f"CHoCH      : {sum(1 for e in res.events if e.kind=='CHoCH')}\n"
                f"FVG còn mở : {sum(1 for g in res.fvgs if not g.mitigated)}\n"
                f"Order Block: {len(res.order_blocks)}")

    # ----- Bảng chấm điểm hợp lưu -----
    st.divider()
    st.subheader("🎯 Hợp lưu (Confluence)")
    st.caption("Càng nhiều yếu tố trùng nhau cùng hướng → kèo càng chất. Mục đích là "
               "LỌC bớt kèo rác, không phải để vào nhiều.")
    conf = score_confluence(df, res, decision)
    if conf.direction == "—":
        st.info(conf.verdict)
    else:
        # thanh điểm + checklist
        color = "🟢" if conf.score >= 4 else ("🟡" if conf.score >= 3 else "🔴")
        st.markdown(f"### {color} {conf.score}/6 — {conf.direction}")
        cc1, cc2 = st.columns(2)
        half = (len(conf.factors) + 1) // 2
        for col, group in [(cc1, conf.factors[:half]), (cc2, conf.factors[half:])]:
            with col:
                for f in group:
                    mark = "✅" if f.passed else "⬜"
                    st.markdown(f"{mark} **{f.name}**  \n<span style='color:#9fb0c0;font-size:12px'>{f.note}</span>",
                                unsafe_allow_html=True)
        st.caption(conf.verdict + "  ·  ⚠️ Điểm cao KHÔNG đảm bảo thắng — vẫn phải quản lý vốn.")

    # ----- Quét nhiều mã (Confluence Scanner) -----
    st.divider()
    st.subheader("🔍 Quét nhiều mã")
    st.caption("Chấm điểm hợp lưu cho cả nhóm mã, xếp hạng mã nào đang 'chín' nhất — "
               "khỏi phải soi từng cái. Quét hơi lâu vì mỗi mã tải dữ liệu riêng.")

    scan_groups = st.multiselect("Chọn nhóm để quét", list(FULL_CATALOG.keys()),
                                 default=[group] if isinstance(group, str) and group in FULL_CATALOG else [])
    if st.button("🔍 Quét ngay"):
        items = []
        for g in scan_groups:
            for nm, (mk, sym) in FULL_CATALOG[g].items():
                items.append((nm, mk, sym))
        if not items:
            st.warning("Chọn ít nhất một nhóm để quét.")
        else:
            prog = st.progress(0.0, text="Đang quét…")
            rows = []
            for i, (nm, mk, sym) in enumerate(items, 1):
                r = scan_one(nm, mk, sym, timeframe, htf_rule, lookback, min_atr,
                             require_sweep, min_rr)
                if r:
                    rows.append(r)
                prog.progress(i / len(items), text=f"Đang quét… {i}/{len(items)} ({nm})")
            prog.empty()
            if rows:
                ranked = rank(rows)
                for r in ranked:
                    r["Giá"] = fmt_price(r["Giá"])
                    r["R:R"] = r["R:R"] if r["R:R"] is not None else "—"
                    # gộp vùng vào + SL + TP thành cột dễ đọc
                    if r.get("_entry_bottom") is not None:
                        r["Vùng vào"] = f"{fmt_price(r['_entry_bottom'])}–{fmt_price(r['_entry_top'])}"
                        r["SL"] = fmt_price(r["_sl"])
                        r["TP"] = fmt_price(r["_tp"])
                    else:
                        r["Vùng vào"] = r["SL"] = r["TP"] = "—"
                    for k in ("_score", "_entry_top", "_entry_bottom", "_sl", "_tp"):
                        r.pop(k, None)
                st.session_state["scan_rows"] = ranked
                st.success(f"Quét xong {len(items)} mã, có dữ liệu {len(rows)} mã. "
                           f"Xếp theo điểm hợp lưu giảm dần:")
            else:
                st.error("Không lấy được dữ liệu mã nào (kiểm tra mạng / cài thư viện).")

    if st.session_state.get("scan_rows"):
        st.dataframe(st.session_state["scan_rows"], use_container_width=True, hide_index=True)
        st.caption("⚠️ Điểm cao = nhiều yếu tố hội tụ, KHÔNG phải đảm bảo thắng. "
                   "Chọn mã điểm cao rồi xem chart kỹ + quản lý vốn trước khi quyết định.")

    # ----- Cảnh báo (watchlist) -----
    st.divider()
    st.subheader("🔔 Cảnh báo khi giá gần vùng vào")
    st.caption("Chọn mã để worker (chạy nền) theo dõi và báo qua Telegram khi giá gần entry. "
               "Worker chạy bằng lệnh riêng: python watcher.py (xem hướng dẫn bên dưới).")

    wl.init_db()
    cwa, cwb = st.columns([2, 1])
    with cwa:
        near_pct = st.slider("Báo khi giá cách entry dưới (%)", 0.1, 3.0, 0.5, step=0.1)
    with cwb:
        st.write(""); st.write("")
        if is_real and st.button("➕ Thêm mã đang xem vào theo dõi"):
            wl.add(symbol, market, symbol, timeframe, htf_rule, near_pct)
            st.success(f"Đã thêm {symbol} vào danh sách theo dõi.")
        elif not is_real:
            st.caption("Chuyển sang 'Dữ liệu thật' để thêm mã.")

    watch = wl.list_all()
    if watch:
        st.write("**Đang theo dõi:**")
        for w in watch:
            wc1, wc2, wc3 = st.columns([4, 1, 1])
            status = "🟢" if w.enabled else "⚪"
            wc1.write(f"{status} **{w.name}** ({w.symbol}) · {w.timeframe} · báo khi <{w.near_pct}%")
            if wc2.button("Tắt/Bật", key=f"tg{w.id}"):
                wl.set_enabled(w.id, not w.enabled); st.rerun()
            if wc3.button("Xoá", key=f"rm{w.id}"):
                wl.remove(w.id); st.rerun()
    else:
        st.info("Chưa có mã nào. Chọn mã thật ở trên rồi bấm '➕ Thêm mã đang xem'.")

    with st.expander("📱 Cách bật cảnh báo Telegram"):
        st.markdown("""
**Làm 1 lần:**
1. Mở Telegram, tìm **@BotFather** → gõ `/newbot` → đặt tên → nhận **TOKEN**.
2. Nhắn 1 tin bất kỳ cho bot vừa tạo.
3. Vào `https://api.telegram.org/bot<TOKEN>/getUpdates` → tìm `"chat":{"id": ...}` → đó là **CHAT ID**.

**Chạy worker** (mở cmd tại thư mục app):
```
set TELEGRAM_TOKEN=token_của_bạn
set TELEGRAM_CHAT_ID=chat_id_của_bạn
python watcher.py
```
Worker quét mỗi 2 phút, nhắn Telegram khi có mã gần vùng vào.
Chỉ cần worker chạy — **không cần mở app này**. (Máy phải bật.)
        """)

    # ----- Quản lý vốn -----
    st.divider()
    st.subheader("💰 Quản lý vốn")
    st.caption("Tính khối lượng vào lệnh để nếu thua chỉ mất đúng % vốn bạn đặt. "
               "Đây là thứ cứu tài khoản hơn mọi setup đẹp.")

    # tự điền giá từ lệnh gợi ý nếu có
    p = decision.plan
    def_entry = float((p.entry_top + p.entry_bottom) / 2) if p else float(decision.last_price)
    def_sl = float(p.stoploss) if p else float(decision.last_price * 0.98)
    def_tp = float(p.takeprofit) if p else float(decision.last_price * 1.04)

    rc1, rc2, rc3 = st.columns(3)
    balance = rc1.number_input("Vốn (tài khoản)", min_value=0.0, value=1000.0, step=100.0)
    risk_pct = rc2.number_input("Rủi ro mỗi lệnh (%)", min_value=0.1, max_value=10.0,
                                value=1.0, step=0.5,
                                help="Khuyến nghị 1–2%. Càng cao càng dễ cháy khi chuỗi thua.")
    leverage = rc3.number_input("Đòn bẩy", min_value=1.0, max_value=125.0, value=1.0, step=1.0,
                                help="1 = không đòn bẩy (cổ phiếu). Crypto/forex có thể >1.")

    rc4, rc5, rc6 = st.columns(3)
    entry_in = rc4.number_input("Giá vào", value=def_entry, format="%.6f")
    sl_in = rc5.number_input("Giá cắt lỗ (SL)", value=def_sl, format="%.6f")
    tp_in = rc6.number_input("Giá chốt lời (TP)", value=def_tp, format="%.6f")

    try:
        from smc.risk import position_size, survival
        pos = position_size(balance, risk_pct, entry_in, sl_in, tp_in, leverage)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Số tiền rủi ro", f"{pos.risk_amount:,.2f}")
        k2.metric("Khối lượng vào", f"{pos.size:,.4f}".rstrip("0").rstrip("."))
        k3.metric("Giá trị lệnh", f"{pos.position_value:,.2f}")
        k4.metric("Ký quỹ cần", f"{pos.margin_required:,.2f}")
        st.caption(f"Nếu trúng TP: lời ~ **{pos.reward_amount:,.2f}** (R:R {pos.rr:.2f}). "
                   f"Nếu thua: mất đúng **{pos.risk_amount:,.2f}** ({risk_pct}% vốn). "
                   f"Chịu 10 lệnh thua liên tiếp còn **{survival(balance, risk_pct, 10):.1f}%** vốn.")
    except Exception as e:
        st.warning(f"Chưa tính được: {e}")

    # ----- Trợ lý AI -----
    st.divider()
    st.subheader("🤖 Trợ lý AI")
    if not api_key:
        st.caption("Nhập Anthropic API key ở sidebar để bật diễn giải & hỏi đáp bằng AI. "
                   "AI chỉ diễn giải dữ kiện, không dự đoán giá.")
    else:
        ctx = smc_ai.build_context(symbol if is_real else "Mô phỏng",
                                   timeframe if is_real else "—",
                                   decision, wyckoff, res)
        ai1, ai2 = st.columns([1, 2])
        with ai1:
            if st.button("📝 Nhờ AI diễn giải"):
                with st.spinner("AI đang đọc nhận định…"):
                    try:
                        st.session_state["ai_text"] = smc_ai.interpret(api_key, ctx)
                    except Exception as e:
                        st.session_state["ai_text"] = f"Lỗi gọi AI: {e}"
        with ai2:
            q = st.text_input("Hỏi AI về chart / khái niệm",
                              placeholder="VD: tại sao bias đang là giảm? spring là gì?")
            if st.button("Hỏi AI") and q:
                with st.spinner("AI đang trả lời…"):
                    try:
                        st.session_state["ai_text"] = smc_ai.ask(api_key, ctx, q)
                    except Exception as e:
                        st.session_state["ai_text"] = f"Lỗi gọi AI: {e}"
        if st.session_state.get("ai_text"):
            st.info(st.session_state["ai_text"])

    # ----- Backtest -----
    st.divider()
    st.subheader("Kiểm chứng (Backtest)")
    st.caption("Chạy thử logic trên chính dữ liệu đang xem. Nên có >300 nến mới đủ ý nghĩa.")

    cf1, cf2 = st.columns(2)
    fee = cf1.slider("Phí mỗi chiều (%)", 0.0, 0.2, 0.04, step=0.01,
                     help="Phí giao dịch mỗi lần vào/ra. Crypto taker ~0.04%, "
                          "chứng khoán/forex tuỳ sàn.") / 100
    slip = cf2.slider("Trượt giá mỗi chiều (%)", 0.0, 0.2, 0.05, step=0.01,
                      help="Giá khớp thực tế lệch so với kỳ vọng. Càng kém thanh khoản càng cao.") / 100

    st.caption("Backtest CHẠY TỰ ĐỘNG — máy thay bạn giả lập mọi lệnh trong quá khứ "
               "(bạn không bấm từng lệnh). Thứ BẠN điều khiển: phí, trượt giá, bộ lọc "
               "cú quét (sidebar), và mã/khung thời gian. Sau khi chạy, kéo xuống xem "
               "bảng CHI TIẾT TỪNG LỆNH để biết máy đã vào những lệnh nào.")

    b1, b2 = st.columns(2)
    run1 = b1.button("▶ Chạy kiểm chứng (giai đoạn này)")
    run2 = b2.button("📊 Kiểm tra độ ổn định (nhiều giai đoạn)")

    if run1:
        with st.spinner("Đang mô phỏng lệnh trên lịch sử…"):
            bt = run_backtest(df, htf_rule=htf_rule, warmup=min(120, len(df)//3),
                              fee_pct=fee, slippage_pct=slip, require_sweep=require_sweep, min_rr=min_rr)
        if bt.n == 0:
            st.info("Không có lệnh nào được kích hoạt — thử dữ liệu dài hơn.")
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Số lệnh", bt.n)
            m2.metric("Tỉ lệ thắng", f"{bt.win_rate*100:.1f}%")
            m3.metric("Tổng R (đã trừ phí)", f"{bt.total_r:+.2f}")
            m4.metric("Hệ số lời", f"{bt.profit_factor:.2f}")
            eq = go.Figure(go.Scatter(y=bt.equity_curve, mode="lines",
                                      line=dict(color="#3a8fff")))
            eq.update_layout(template="plotly_dark", height=240,
                             margin=dict(l=10, r=10, t=10, b=10),
                             paper_bgcolor="#0a0e14", plot_bgcolor="#0a0e14",
                             title="Đường vốn (tổng R tích luỹ, đã trừ phí)")
            st.plotly_chart(eq, use_container_width=True)

            # bảng liệt kê TỪNG lệnh — để bạn thấy máy đã vào những lệnh nào
            st.markdown("**Chi tiết từng lệnh** (máy đã giả lập):")
            trade_rows = []
            for i, tr in enumerate(bt.trades, 1):
                t_in = df.index[tr.open_idx].strftime("%Y-%m-%d %H:%M")
                t_out = df.index[tr.close_idx].strftime("%Y-%m-%d %H:%M")
                trade_rows.append({
                    "#": i,
                    "Hướng": tr.direction,
                    "Vào lúc": t_in,
                    "Giá vào": fmt_price(tr.entry),
                    "Đóng lúc": t_out,
                    "Kết quả": "✅ Thắng" if tr.result == "win" else "❌ Thua",
                    "R": round(tr.r_realized, 2),
                })
            st.dataframe(trade_rows, use_container_width=True, hide_index=True)
            st.caption("⚠️ Kết quả đẹp một lần không đảm bảo tương lai. Dùng nút 'Kiểm tra "
                       "độ ổn định' để xem logic có lời đều qua nhiều giai đoạn không.")

    if run2:
        with st.spinner("Đang chạy nhiều giai đoạn…"):
            stab = run_stability(df, n_segments=4, htf_rule=htf_rule,
                                 window=200, fee_pct=fee, slippage_pct=slip,
                                 require_sweep=require_sweep, min_rr=min_rr)
        if not stab.segments:
            st.info("Dữ liệu quá ngắn để chia giai đoạn — cần dài hơn (nên >800 nến).")
        else:
            rows = [{"Giai đoạn": name, "Số lệnh": bt.n,
                     "Tỉ lệ thắng": f"{bt.win_rate*100:.0f}%",
                     "Tổng R": round(bt.total_r, 2)}
                    for name, bt in stab.segments]
            st.dataframe(rows, use_container_width=True, hide_index=True)
            st.text(stab.summary())


if __name__ == "__main__":
    main()
