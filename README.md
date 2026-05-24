# SMC + Wyckoff Analyzer

Công cụ phân tích biểu đồ theo **Smart Money Concepts (SMC)** và **Wyckoff**:
nhận diện cấu trúc thị trường, đưa ra nhận định, vùng vào lệnh, vùng giằng co,
và **backtest** để kiểm chứng.

> ⚠️ Đây là công cụ **tham khảo**, KHÔNG phải lời khuyên đầu tư. Luôn backtest
> và tự chịu trách nhiệm với quyết định của mình.

## Cài đặt

```bash
pip install -r requirements.txt
```

## Chạy app

```bash
streamlit run app.py
```

Mở trình duyệt theo link Streamlit in ra. Chưa có mạng / chưa cài data lib?
Chọn **"Dữ liệu mô phỏng"** ở sidebar để thử ngay.

## Cấu trúc dự án

```
smc_app/
├── app.py              # Phần 7 — giao diện Streamlit (ghép tất cả)
├── requirements.txt
└── smc/
    ├── data.py         # Phần 1 — lấy & chuẩn hoá nến (crypto/stock/forex)
    ├── engine.py       # Phần 2 — swing, BOS/CHoCH, FVG, Order Block
    ├── mtf.py          # Phần 3 — multi-timeframe, điểm hợp lưu
    ├── decision.py     # Phần 4 — bias, vùng vào, SL/TP, R:R, vùng giằng co
    ├── wyckoff.py      # Phần 6 — trading range, spring, upthrust
    └── backtest.py     # Phần 5 — kiểm chứng walk-forward
```

## Dùng bằng code (không qua UI)

```python
from smc.data import get_candles
from smc.decision import decide
from smc.wyckoff import analyze_wyckoff
from smc.backtest import run_backtest

df = get_candles("crypto", "BTC/USDT", "1h")

print(decide(df, htf_rule="4h").summary())   # nhận định SMC
print(analyze_wyckoff(df).note)              # gợi ý Wyckoff
print(run_backtest(df, htf_rule="4h").summary())  # backtest
```

## Lưu ý quan trọng (đọc kỹ)

- **Logic đã được đơn giản hoá để dễ hiểu & dễ mở rộng.** Muốn dùng thật cần
  cải tiến: lọc swing theo độ lớn, phân biệt internal vs swing structure, lọc
  tín hiệu theo phiên giao dịch, v.v.
- **Backtest đẹp một lần không chứng minh gì.** Trên dữ liệu ngẫu nhiên, kết quả
  dao động quanh số 0. Hãy chạy nhiều mã / nhiều giai đoạn; nếu tổng R không
  dương ổn định thì logic chưa có lợi thế thật.
- **Cẩn thận overfitting:** đừng chỉnh tham số cho tới khi quá khứ đẹp. Chia
  dữ liệu: tối ưu một đoạn, kiểm tra đoạn khác.
- **Wyckoff chỉ là gợi ý thiên hướng**, không phải hệ thống độc lập. Mạnh nhất
  khi SMC và Wyckoff đồng thuận.
```
