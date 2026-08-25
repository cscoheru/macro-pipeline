# PR-4 Prompt 对齐 v3 试跑报告

> **执行**：CC / 本地流水线（2026-08-25 UTC）  
> **对照**：`reviews/PR4_PROMPT_ALIGN_V3_KICKOFF_2026-08-25.md`  
> **审验**：Cursor 复验（用户「审验」）

---

## 用户摘要

| 项 | 结果 |
|----|------|
| **试跑视频** | `7DsxtHsOCzA` |
| **analyze** | success（`hcrun_01a03670aa7e7001b0878f18e865a521`，deepseek） |
| **validate** | partial — **validated=4**, rejected=4 |
| **门禁 validated≥1** | **通过** |
| **render `--from-db`** | 本地 Markdown 含 4 条主张 |
| **publish** | **未在 v3 后重跑**（Obsidian SHA 仍为旧版） |
| **pytest** | 387 passed |
| **store.db** | `3c2ceda61c24…`（无漂移） |

---

## 1. 与 v2 对比

| 指标 | v2 | v3 |
|------|----|----|
| accepted（本 run） | 0 | **4** |
| rejected（本 run） | 8 | 4 |
| R10（speaker_statement） | 50% | **0%** |
| R2（verbatim quote） | 50% | **100%**（仅拒因） |

Schema 删除 `speaker_statement` 后 R10 **归零**；剩余拒因为 R2。

---

## 2. accepted 样例（本 run）

| claim_text | exact_quote | layer |
|------------|-------------|-------|
| Kimi K3是一个做题家AI。 | 是一个做题家 | speaker_reasoning |
| 做题家AI不一定没有用。 | 做题家不一定没有用 | speaker_reasoning |
| K3做小任务非常贵且token消耗快。 | 做小任务非常贵 | speaker_reasoning |
| K3的token效率很差。 | 这就是它的token efficiency很差 | speaker_reasoning |

`prompt_version`: `2026-08-25.2`

---

## 3. render 产物

路径：`data/houchen/publish/render/2026-08-24.1/video/7DsxtHsOCzA.md`

- `claim_count_accepted`: 4
- `render_sha256`: `9c8bbc4d7ca0abc3d89b34c2a2a026ea43ac48ce781b913040fff2931533d3d9`
- 声明列表非空（4 条 `### hccl_…`）

---

## 4. publish 缺口

`publish_record` 中 `7DsxtHsOCzA`：

- `vault_sha256`: `c68079e2…`（2026-08-24 旧版）
- 当前 render 文件 SHA: `9c8bbc4d…`

**Obsidian 尚未反映 v3 主张列表**（需 re-publish）。

---

## 5. 红线

- `houchen_validator` / `houchen_quote` 未改动
- S-4 macro isolation：14 passed

---

## 6. 建议下一步

1. `publish --kind video` 单页或含 `7DsxtHsOCzA` 的 batch
2. 门禁通过后按 kickoff §3 扩 7 视频（`--no-pending` 逐条）
3. R2 仍占拒因 100% — 可观察扩量后占比，再决定是否 prompt 微调或授权 R2 repair
