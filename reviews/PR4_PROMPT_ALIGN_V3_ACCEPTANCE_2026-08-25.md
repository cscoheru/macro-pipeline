# PR-4 Prompt 对齐 v3 审验（Cursor）

> **签发**：Cursor（2026-08-25）  
> **对照**：`reviews/PR4_PROMPT_ALIGN_V3_REPORT_2026-08-25.md`  
> **用户触发**：「审验」  
> **代码基线**：`65dcc68`（已 push `origin/main`）

---

## 用户摘要

| 项 | 结果 |
|----|------|
| **v3 工程交付** | **PASS**（schema / prompt / `--from-db` / 测试） |
| **单视频门禁 validated≥1** | **PASS**（4 real accepted） |
| **可读主张 on 本地 render** | **PASS** |
| **Obsidian 同步** | **PASS**（publish 2026-08-25，`vault_sha` = `render_sha`） |
| **裁定** | **PASS**（7 视频扩量完成，2026-08-25） |

---

## 1. 工程复验（commit `65dcc68`）

| 检查项 | 结果 |
|--------|------|
| `claim.layer` enum 无 `speaker_statement` | ✅ |
| `PROMPT_VERSION=2026-08-25.2` + v3 few-shot | ✅ |
| INPUT 含 `raw_caption_sha256` | ✅ |
| `build_video_page_from_db` + `render --from-db` | ✅ |
| pytest | **387 passed** |
| `test_houchen_macro_isolation` (S-4) | **14 passed** |
| `data/store.db` SHA | `3c2ceda61c24…`（无变） |

---

## 2.  live 试跑复验（`7DsxtHsOCzA`）

```text
analyze run_id     hcrun_01a03670aa7e7001b0878f18e865a521  → success
validate           validated=4, rejected=4, needs_review=0
拒因（本 run 4 条 rejected）  100% R2，0% R10
库内本视频 accepted           4（均为本 run real）
本地 render SHA               9c8bbc4d…（4 条声明列表）
publish_record vault_sha      c68079e2…（≠ render，Obsidian 旧版）
```

与报告一致。

---

## 3. v3 相对 v2 的确认

| 假设 | 审验 |
|------|------|
| Schema 去掉 `speaker_statement` → R10 下降 | ✅ 本 run 0 R10 |
| Few-shot + 算法 → 出现 real accepted | ✅ 4 accepted |
| `--from-db` → 页面可读主张 | ✅ 本地 Markdown |

**R2 仍为唯一拒因**（4/8 候选）；属预期内 prompt 纪律问题，非 schema 矛盾。

---

## 4. 未通过项

| 项 | 说明 |
|----|------|
| **publish 后 Obsidian** | kickoff 要求 publish；当前 vault SHA 落后于 render |
| **CC 正式交卷** | 无 CC 署名 REPORT；Cursor 据 DB + 文件复验补档 |
| **全量 7 视频** | kickoff §3 明确「门禁通过后再做」— 尚未启动 |

---

## 5. Verdict

**PR-4 PROMPT ALIGN v3 — PARTIAL（Cursor 2026-08-25）。**

- **工程 + 门禁 + 本地 render**：通过  
- **端到端 Obsidian**：未通过（缺 v3 后 publish）

**不建议**在未 publish 的情况下宣称「路线 2 可读主张已上线」；**可以**在补 publish 后启动 7 视频扩量。

---

## 6. 下一步（用户裁定）

| 你说 | 方向 |
|------|------|
| **publish** | CC：`publish --kind video` 更新 `7DsxtHsOCzA`（及可选 7 页 batch） |
| **扩量** | publish 通过后 kickoff §3 逐视频 analyze→validate→render→publish |
| **commit** | 审验文档 + HANDOFF 入库 |
| **调 R2** | 需明确授权（校验器 / repair 路径） |
