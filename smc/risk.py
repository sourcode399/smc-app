"""
smc/risk.py — QUẢN LÝ VỐN (position sizing)
============================================
Công cụ THỰC TẾ nhất cho trader: tính xem được vào lệnh bao nhiêu để nếu thua
chỉ mất đúng X% tài khoản. Đây là thứ cứu tài khoản hơn mọi setup đẹp.

Nguyên lý: rủi ro cố định mỗi lệnh.
    Số tiền rủi ro = vốn × %rủi ro
    Rủi ro mỗi đơn vị = |giá vào − giá cắt lỗ|
    Khối lượng = Số tiền rủi ro ÷ Rủi ro mỗi đơn vị
Nhờ vậy dù SL gần hay xa, mỗi lệnh thua luôn mất đúng X% — không bao giờ cháy
tài khoản vì một lệnh.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PositionPlan:
    risk_amount: float       # số tiền chấp nhận mất (tiền tệ tài khoản)
    risk_per_unit: float     # rủi ro trên 1 đơn vị (|entry - sl|)
    size: float              # khối lượng được vào (số coin/cổ phiếu/lot)
    position_value: float    # giá trị lệnh = size × entry
    margin_required: float   # ký quỹ cần (nếu dùng đòn bẩy)
    reward_amount: float     # lời dự kiến nếu trúng TP
    rr: float                # tỉ lệ R:R


def position_size(balance: float, risk_pct: float,
                  entry: float, stoploss: float,
                  takeprofit: float | None = None,
                  leverage: float = 1.0) -> PositionPlan:
    """
    Tính khối lượng lệnh theo % rủi ro.

        balance    : số dư tài khoản
        risk_pct   : % rủi ro mỗi lệnh (vd 1.0 = 1%)
        entry      : giá vào dự kiến
        stoploss   : giá cắt lỗ
        takeprofit : giá chốt lời (tuỳ chọn, để tính lời dự kiến + R:R)
        leverage   : đòn bẩy (crypto/forex). 1 = không đòn bẩy.
    """
    risk_amount = balance * risk_pct / 100.0
    risk_per_unit = abs(entry - stoploss)
    if risk_per_unit <= 0:
        raise ValueError("Giá vào và giá cắt lỗ phải khác nhau.")

    size = risk_amount / risk_per_unit
    position_value = size * entry
    margin_required = position_value / leverage if leverage > 0 else position_value

    reward_amount, rr = 0.0, 0.0
    if takeprofit is not None:
        reward_per_unit = abs(takeprofit - entry)
        reward_amount = size * reward_per_unit
        rr = reward_per_unit / risk_per_unit if risk_per_unit > 0 else 0.0

    return PositionPlan(risk_amount=risk_amount, risk_per_unit=risk_per_unit,
                        size=size, position_value=position_value,
                        margin_required=margin_required,
                        reward_amount=reward_amount, rr=rr)


def survival(balance: float, risk_pct: float, losses: int) -> float:
    """
    Còn lại bao nhiêu % vốn sau `losses` lệnh thua LIÊN TIẾP (mỗi lệnh mất risk_pct).
    Dùng để hiểu mình chịu được chuỗi thua tới đâu — phần tâm lý + sống còn.
    """
    remaining = balance
    for _ in range(losses):
        remaining -= remaining * risk_pct / 100.0   # rủi ro % trên số dư hiện tại
    return remaining / balance * 100.0


if __name__ == "__main__":
    # python -m smc.risk
    p = position_size(balance=1000, risk_pct=1, entry=100, stoploss=98, takeprofit=106)
    print(f"Rủi ro: {p.risk_amount}$ | mỗi đơn vị: {p.risk_per_unit}")
    print(f"Khối lượng: {p.size} đơn vị | giá trị lệnh: {p.position_value}$")
    print(f"Lời dự kiến nếu trúng TP: {p.reward_amount}$ | R:R {p.rr}")
    print(f"Sau 10 lệnh thua liên tiếp còn: {survival(1000,1,10):.1f}% vốn")
