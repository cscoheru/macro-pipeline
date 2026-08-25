# Corpus Expand — Acceptance (2026-08-25)

> **工单**：`reviews/CORPUS_EXPAND_KICKOFF_2026-08-25.md`  
> **报告**：`reviews/CORPUS_EXPAND_REPORT_2026-08-25.md`  
> **裁决**：PASS

---

## A — 字幕 P1

| 项 | 门禁 | 实测 |
|----|------|------|
| pending | 0 | ✅ |
| coverage | 有 P1 快照 | ✅ `HOUCHEN_CAPTION_COVERAGE_2026-08-25-P1.md` |
| frozen / normalized | — | 53 / 53 |
| missing（terminal） | 允许 | 76（streams 无 CC 符合预期） |
| analyze | 本阶段禁止 | ✅ 未在 A 阶段 analyze |

---

## B — 扩竖切

| 项 | 门禁 | 实测 |
|----|------|------|
| 视频有 accepted | ≥25 | ✅ **39** |
| accepted 合计 | ≥120（尽力） | ✅ **240** |
| 处理上限 | ≤25 新 analyze | ✅ 25（23 成功 +1 fail +1 zero） |
| publish | video pages | ✅ 39 published |
| Obsidian | 抽查 GET | ✅ `hSJE1cVbWQs` HTTP 200；SHA match |
| store.db | 不变 | ✅ `4a8e409b…` |

---

## C — Macro review（PR-5.1）

| 项 | 门禁 | 实测 |
|----|------|------|
| reviewed | ≥10 | ✅ 20 |
| evaluation | ≥10 `macro_bridge` | ✅ 20 |
| CLI | queue / mark / import | ✅ |
| store SHA | 不变 | ✅ |
| tests | 全绿 | ✅ 28 passed |

**备注**：review 工作流尚无新增单测（kickoff C3 要求）；现有 28 测试仍绿。建议后续补 `mark_reviewed` / `import_reviewed` 测试。

---

## 总结

全量字幕 **P1** 完成；竖切 **39** 视频 / **240** claims；macro **20** 条人工决议已入库 evaluation。brief 计划 **P2** 达标；**P3 WPS** 仍等用户导入。
