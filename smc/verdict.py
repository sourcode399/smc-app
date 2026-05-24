from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Verdict:
    direction: str
    level: str
    color: str
    score: int
    lines: list
    advice: str


def summarize(decision, wyckoff, confluence) -> Verdict:
    lines = []
    smc = {"bull": 1, "bear": -1, "neutral": 0}[decision.bias]
    wy = {"accumulation": 1, "distribution": -1, "unclear": 0}[wyckoff.bias_hint]
    conf_dir = {"LONG": 1, "SHORT": -1, "—": 0}[confluence.direction]

    lines.append(f"SMC: {'tăng' if smc>0 else 'giảm' if smc<0 else 'trung lập'}")
    lines.append(f"Wyckoff: {'tích luỹ (nghiêng tăng)' if wy>0 else 'phân phối (nghiêng giảm)' if wy<0 else 'chưa rõ'}")
    lines.append(f"Hợp lưu: {confluence.score}/6"
                 + (f" hướng {confluence.direction}" if conf_dir else ""))

    if smc * wy < 0:
        return Verdict(
            direction="TRUNG LẬP", level="mâu thuẫn", color="yellow",
            score=0, lines=lines,
            advice="⚠️ SMC và Wyckoff NGƯỢC chiều nhau — thị trường đang chuyển tiếp, "
                   "chưa rõ ràng. Nên ĐỨNG NGOÀI, chờ tín hiệu đồng thuận.")

    net = smc + wy
    direction = "TĂNG" if net > 0 else "GIẢM" if net < 0 else "TRUNG LẬP"
    color = "green" if net > 0 else "red" if net < 0 else "yellow"

    agree = abs(net)
    if conf_dir != 0 and ((conf_dir > 0 and net > 0) or (conf_dir < 0 and net < 0)):
        conf_bonus = confluence.score
    else:
        conf_bonus = 0

    if direction == "TRUNG LẬP":
        level = "yếu"
        advice = "Cả SMC lẫn Wyckoff đều chưa rõ hướng — chưa có kèo, chờ thêm."
    elif agree == 2 and conf_bonus >= 4:
        level = "mạnh"
        advice = (f"SMC + Wyckoff + hợp lưu ({conf_bonus}/6) cùng chỉ {direction.lower()} "
                  f"→ kèo {('LONG' if net>0 else 'SHORT')} đáng cân nhắc (vẫn quản lý vốn).")
    elif agree == 2:
        level = "khá"
        advice = (f"SMC và Wyckoff cùng chỉ {direction.lower()}, nhưng hợp lưu mới {confluence.score}/6 "
                  f"→ cân nhắc thận trọng, chờ thêm xác nhận thì chắc hơn.")
    else:
        level = "yếu"
        advice = (f"Chỉ một tín hiệu nghiêng {direction.lower()}, nguồn còn lại chưa rõ "
                  f"→ tín hiệu yếu, nên chờ thêm.")

    return Verdict(direction=direction, level=level, color=color,
                   score=agree + (1 if conf_bonus >= 4 else 0),
                   lines=lines, advice=advice)
