---
name: cut-loser
version: 1
status: active
category: playbook
trigger: Một vị thế vi phạm stop-loss hoặc thesis đã sai
required_skills: [stop-loss-rules, technical-trend]
parent_skill: null
uses: 0
---

## Mục tiêu
Cắt lỗ **nhanh, không lý luận**. Quy trình này chạy mỗi daily job, TRƯỚC khi
research mã mới — để cash/slot không bị giữ bởi vị thế hỏng.

## Rules kích hoạt SELL ngay (không cần Claude phán)

Simulator `check_stop_loss()` tự động đề xuất SELL nếu 1 trong 4:

1. **Hard stop hit**: close hôm nay ≤ stop_loss đã set khi mở vị thế.
2. **Invalidation hit**: điều kiện trong `decisions.invalidation` đã thỏa mãn
   (ví dụ "close < 143,000 sau 2 phiên" đã xảy ra).
3. **Time stop**: đã giữ ≥ 15 phiên, P&L trong ±3%, không có catalyst mới.
4. **Drawdown from peak**: giá hiện tại < 85% đỉnh cục bộ kể từ lúc mở vị thế,
   kể cả khi vẫn +X% so với entry (trailing bị vi phạm).

Proposal từ simulator → Claude xem lại, có quyền **đảo ngược** sang HOLD
nhưng phải:
- Viết `rationale` giải thích vì sao override.
- Thêm condition mới vào `invalidation`.
- Giảm conviction xuống tối đa 3.

## Rules kích hoạt SELL theo Claude đánh giá

5. **Thesis broken**: evidence ban đầu không còn đúng.
   - KQKD công bố miss > 15%.
   - Catalyst bị hủy (ví dụ hợp đồng mất, M&A fail).
   - Ngành chuyển từ dẫn dắt sang lagging.

6. **Better opportunity + cash squeeze**: có mã khác conviction ≥ 4,
   playbook new-entry pass, nhưng không đủ cash và không còn cash buffer.
   - Ưu tiên SELL vị thế conviction thấp nhất + P&L gần breakeven.

## Partial exit (TRIM) thay vì SELL

- Nếu vi phạm rule 4 (drawdown from peak) nhưng chưa chạm hard stop:
  TRIM 50% thay vì SELL toàn bộ.
- Nếu đạt target price 1 nhưng chưa đạt target 2: TRIM 33–50%,
  dời stop về breakeven cho phần còn lại.

## Checklist output

```json
{
  "action": "SELL" | "TRIM",
  "qty": ...,
  "skills_used": ["stop-loss-rules", "technical-trend"],
  "playbook_used": "cut-loser",
  "evidence": [
    "rule triggered: <1|2|3|4|5|6>",
    "close hôm nay = X, stop đã set = Y",
    "invalidation (nếu có) = ...",
    "days held = ..., P&L = ..."
  ],
  "invalidation": "N/A — đây là exit decision"
}
```

## Không làm
- Không "average down" (mua thêm khi lỗ) — vi phạm playbook này.
  Nếu thực sự tin thesis vẫn đúng: đóng vị thế hiện tại, sau N phiên mở lại
  bằng new-entry playbook đầy đủ.
- Không dời stop rộng hơn để "đợi hồi".
- Không skip cut-loser vì "sắp có tin tốt".
