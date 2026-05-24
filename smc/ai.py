"""
smc/ai.py — LỚP AI (diễn giải + hỏi đáp)
=========================================
Dùng Claude API để:
    1) DIỄN GIẢI kết quả engine thành lời tiếng Việt dễ hiểu.
    2) TRẢ LỜI câu hỏi của người dùng về chart / khái niệm SMC-Wyckoff.

NGUYÊN TẮC AN TOÀN (quan trọng):
    - AI CHỈ diễn giải những DỮ KIỆN engine đã tính. KHÔNG được dự đoán giá,
      KHÔNG bịa thêm tín hiệu. Vì mô hình ngôn ngữ không tiên tri được thị trường;
      để nó "phán" giá sẽ tạo ra câu nghe thuyết phục nhưng vô căn cứ -> nguy hiểm.
    - Luôn kèm nhắc "đây là tham khảo, không phải lời khuyên đầu tư".

Cài thư viện:  pip install anthropic
Lấy API key:  https://console.anthropic.com  (mục API Keys)
"""

from __future__ import annotations

# model rẻ & nhanh, đủ tốt cho việc diễn giải (xem console.anthropic.com để biết giá)
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """Bạn là trợ lý phân tích kỹ thuật theo Smart Money Concepts (SMC) và Wyckoff,
nói tiếng Việt, giọng gần gũi và rõ ràng.

QUY TẮC BẮT BUỘC:
- CHỈ diễn giải dựa trên DỮ KIỆN được cung cấp. KHÔNG bịa thêm số liệu hay tín hiệu.
- TUYỆT ĐỐI KHÔNG dự đoán giá sẽ lên hay xuống, không hứa hẹn lợi nhuận.
- Mô tả tình huống thị trường và các KỊCH BẢN có thể xảy ra (nếu giá làm X thì...).
- Nếu dữ kiện chưa rõ ràng, hãy nói thẳng là "chưa rõ, nên đứng ngoài".
- Ngắn gọn, đi thẳng vào trọng tâm. Kết thúc bằng câu nhắc đây là phân tích tham khảo,
  không phải lời khuyên đầu tư, người đọc tự chịu trách nhiệm quyết định."""


def build_context(symbol, timeframe, decision, wyckoff, res) -> str:
    """Đóng gói kết quả engine thành đoạn dữ kiện gọn để đưa cho AI."""
    lines = [f"Tài sản: {symbol} | Khung: {timeframe}",
             f"Giá hiện tại: {decision.last_price:.4f}",
             f"Bias (khung lớn): {decision.bias}",
             f"Khung nhỏ đồng thuận khung lớn: {'có' if decision.aligned else 'không'}",
             f"Đang giằng co (range): {'có' if decision.in_range else 'không'}",
             f"Ghi chú khung lớn: {decision.htf_note}"]

    if decision.plan:
        p = decision.plan
        lines.append(f"Lệnh gợi ý: {p.direction}, vùng vào {p.entry_bottom:.4f}–{p.entry_top:.4f}, "
                     f"SL {p.stoploss:.4f}, TP {p.takeprofit:.4f}, R:R {p.rr}")
    else:
        lines.append("Lệnh gợi ý: chưa có (đứng ngoài)")

    lines.append(f"Wyckoff: {wyckoff.bias_hint} — {wyckoff.note}")

    # vài dữ kiện cấu trúc gần nhất
    n_bos = sum(1 for e in res.events if e.kind == "BOS")
    n_ch = sum(1 for e in res.events if e.kind == "CHoCH")
    ob_live = sum(1 for o in res.order_blocks if not o.mitigated)
    sweeps_up = sum(1 for s in res.sweeps if s.direction == "up")
    sweeps_dn = sum(1 for s in res.sweeps if s.direction == "down")
    lines.append(f"Cấu trúc: {n_bos} BOS, {n_ch} CHoCH | Order Block còn hiệu lực: {ob_live}")
    lines.append(f"Cú quét thanh khoản: {sweeps_up} quét đáy (bullish), {sweeps_dn} quét đỉnh (bearish)")
    return "\n".join(lines)


def _call(api_key: str, model: str, user_content: str, max_tokens: int = 700) -> str:
    """Gọi Claude API. Ném lỗi rõ ràng nếu thiếu thư viện/khoá."""
    try:
        import anthropic
    except ImportError as e:
        raise ImportError("Chưa cài thư viện. Chạy:  pip install anthropic") from e
    if not api_key:
        raise ValueError("Chưa nhập API key. Lấy ở https://console.anthropic.com")

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model, max_tokens=max_tokens, system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}])
    # gộp các khối text trong câu trả lời
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()


def interpret(api_key: str, context: str, model: str = DEFAULT_MODEL) -> str:
    """Nhờ AI diễn giải nhận định hiện tại thành lời."""
    prompt = ("Đây là kết quả phân tích kỹ thuật tự động. Hãy diễn giải thành 1 đoạn "
              "ngắn gọn, dễ hiểu cho người dùng: thị trường đang ở trạng thái nào, các "
              "tín hiệu đồng thuận/mâu thuẫn ra sao, và những kịch bản cần theo dõi.\n\n"
              f"DỮ KIỆN:\n{context}")
    return _call(api_key, model, prompt)


def ask(api_key: str, context: str, question: str, model: str = DEFAULT_MODEL) -> str:
    """Trả lời câu hỏi của người dùng, có kèm dữ kiện chart hiện tại làm ngữ cảnh."""
    prompt = (f"Dữ kiện chart hiện tại:\n{context}\n\n"
              f"Câu hỏi của người dùng: {question}\n\n"
              "Trả lời dựa trên dữ kiện trên và kiến thức SMC/Wyckoff. Nếu câu hỏi đòi "
              "dự đoán giá, hãy giải thích vì sao không nên dự đoán và chuyển sang mô tả kịch bản.")
    return _call(api_key, model, prompt)
