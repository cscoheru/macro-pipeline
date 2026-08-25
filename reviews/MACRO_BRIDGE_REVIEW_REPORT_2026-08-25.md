# Macro Bridge Review Report (2026-08-25)

## 试点 Review

| 项 | 值 |
|----|-----|
| Queue size | 347 unreviewed |
| Reviewed | **20** ✅ |
| Evaluation imported | **20** ✅ |
| Store SHA | `4a8e409b…` unchanged ✅ |

## 门禁

- ≥10 reviewed ✅ (20)
- ≥10 evaluation (macro_bridge) ✅ (20)
- store.db SHA unchanged ✅

## CLI

```bash
# 导出队列
python3 scripts/houchen_pipeline.py macro-bridge --review-queue N [--review-queue-md]

# 标记 reviewed
python3 scripts/houchen_pipeline.py macro-bridge --mark-reviewed ID [--relation R]

# 导入 evaluation
python3 scripts/houchen_pipeline.py macro-bridge --import-reviewed N
```

## 文件

- `reviews/MACRO_BRIDGE_REVIEW_QUEUE_2026-08-25.md` (20 candidates)
- `reviews/MACRO_BRIDGE_REVIEW_DECISIONS_2026-08-25.jsonl` (20 decisions)