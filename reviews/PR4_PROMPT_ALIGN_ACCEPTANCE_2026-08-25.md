# PR-4 Prompt 对齐 v2 审验（Cursor）

> **签发**：Cursor（2026-08-25）  
> **对照**：`reviews/PR4_PROMPT_ALIGN_REPORT_2026-08-25.md`  
> **用户触发**：「审验」

---

## 用户摘要

| 项 | 结果 |
|----|------|
| **v2 试跑** | 完成（`7DsxtHsOCzA`） |
| **门禁** | **未通过**（0 real accepted） |
| **进展** | R1（缺 `raw_caption_sha256`）已消除 |
| **Obsidian** | 无变化（仍无主张列表） |
| **裁定** | **PARTIAL** — 方向对，需 v3 |

---

## 1. 复验

```text
试跑视频           7DsxtHsOCzA
analyze            success (deepseek-chat)
validate           partial — validated=0, rejected=8（本 run）
claim 库总计       accepted 3（fake）/ rejected 277
Obsidian 7DsxtHsOCzA  claim_count_accepted: 0
pytest             386 passed
store.db           3c2ceda…（无变）
```

与 CC 报告一致。

---

## 2. 拒因（本 run 8 条）

| 规则 | 占比 | 含义 |
|------|------|------|
| **R10** | 50% | 模型输出 `layer=speaker_statement` |
| **R2** | 50% | `exact_quote` 不是 segment 子串 |

v2 prompt 已写「禁止 speaker_statement」，但 **50% R10 仍出现**。

---

## 3. 根因（Cursor 补充）

**JSON Schema 与 prompt 矛盾**：`houchen_prompt.analysis_input_json_schema()` 里 `claim_candidate.layer` 的 `enum` **仍包含 `speaker_statement`**。DeepSeek 的 system prompt 附带完整 schema，模型被 schema **合法化** 该取值，与 markdown prompt 冲突。

**R2** 仍依赖模型「verbatim 复制」纪律；无 schema 级约束，仅靠 prompt 不够。

---

## 4. v2 有效部分

- INPUT bundle 含 `raw_caption_sha256` → 新 run 不再 R1
- Prompt 算法 / 3–8 条上限 / 正反例 — 结构正确
- 红线、测试 — 绿

---

## 5. Verdict

**PR-4 PROMPT ALIGN v2 — PARTIAL（Cursor 2026-08-25）。**

门禁未过；**不建议**在未修 schema 的情况下全量重跑 7 视频。

---

## 6. v3 建议（下一步 kickoff）

| 优先级 | 动作 |
|--------|------|
| P0 | 从 **模型输出 schema** 的 `claim.layer` enum **删除 `speaker_statement`**（仅留 `speaker_reasoning` / `system_evaluation`） |
| P1 | Prompt 增加 1–2 条 **few-shot**（含 verbatim `exact_quote`） |
| P2 | 单视频重试同一门禁；通过后再 render（DB 填 claims）+ publish |

可选（未授权前不做）：校验前对 `exact_quote` 做 segment 内最长匹配修复（会弱化 R2，需你裁定）。

---

## 7. 未 commit

Cursor v2 改动（prompt、`PROMPT_VERSION`、`raw_caption_sha256`）仍在 working tree；审验报告与 kickoff 为 untracked。可说 **commit** 一并入库。
