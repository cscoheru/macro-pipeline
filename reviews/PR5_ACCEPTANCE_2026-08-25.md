# PR-5 Acceptance (2026-08-25)

> **工单**：`reviews/CONCEPT_REFRESH_PR5_LAND_KICKOFF_2026-08-25.md` §B  
> **计划**：`docs/plans/pr5-macro-bridge.md`  
> **裁决**：PASS — brief §16 PR-5 **关闭**

---

## 门禁

| 项 | 标准 | 结果 |
|----|------|------|
| tests | `test_macro_bridge` 全绿 | ✅ 28 passed |
| store SHA | == `4a8e409b…` | ✅ `--verify-sha` match |
| scan | candidates；零写 store | ✅ `macro_link_candidate` 347（多次 scan 累积） |
| git | PR-5 在 `main` | ✅ `814d8a8` + `d91a8be` |
| 排除 | 无 `asr_transcribe.py` | ✅ |
| 概念刷新 | §A PASS | ✅ |

## Commits（`origin/main`）

```text
814d8a8 feat(houchen): land PR-5 macro-bridge
d91a8be feat(houchen): WPS import-transcript path
```

## 能力摘要

- `macro-bridge --scan / --export / --verify-sha`
- 只读 `store.db`；候选写入 `houchen.sqlite3`
- v1 关系默认 `contextualizes`
