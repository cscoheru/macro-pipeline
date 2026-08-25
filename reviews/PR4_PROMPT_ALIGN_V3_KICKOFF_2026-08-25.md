# Claude Code — Prompt 对齐 v3 + 单视频试跑

> **签发**：Cursor（2026-08-25）  
> **触发**：用户「v3」  
> **前置**：`PR4_PROMPT_ALIGN_ACCEPTANCE`（v2 PARTIAL，0 accepted；根因 schema 含 `speaker_statement`）

---

## 用户摘要

v3 已落地：**模型输出 schema** 的 `claim.layer` enum 已删除 `speaker_statement`；prompt bump 至 v3 + few-shot；`PROMPT_VERSION=2026-08-25.2`；新增 `build_video_page_from_db` + `render --from-db`。

请 **单视频试跑**，门禁：**≥1 real accepted claim** → render（DB）→ publish。

---

## 0. 同步

```bash
cd /Users/kjonekong/macro-pipeline
git pull   # 或合并 Cursor 本地改动
python3 -m pytest scripts/test_houchen_analyzer.py -q
```

---

## 1. 试跑视频

`7DsxtHsOCzA`（v2 已试跑；用 `--no-pending` 强制新 analyze run）

```bash
export PROVIDER=deepseek   # 与 config/houchen_analyze.env 一致

python3 scripts/houchen_pipeline.py analyze \
  --live-smoke-allow --provider "$PROVIDER" \
  --no-pending --video-id 7DsxtHsOCzA

python3 scripts/houchen_pipeline.py validate --live-smoke-allow --video-id 7DsxtHsOCzA
```

**门禁**：`validate` summary 中 `validated` ≥ 1（real accepted，非 fake 遗留 3 条）。

若仍 0：在 HANDOFF 记录 **R2/R5 拒因占比**（sqlite 查最新 rejected），停等 Cursor。

---

## 2. 通过后：render + publish（从 DB 读 claims）

```bash
python3 scripts/houchen_pipeline.py render \
  --kind video --page-key 7DsxtHsOCzA --from-db --apply

python3 scripts/houchen_pipeline.py publish \
  --kind video --apply --operator-authorized --actor prompt-align-v3-smoke
```

Obsidian：`Research/世界苦茶/video/7DsxtHsOCzA.md` 应出现 **声明列表**（非「无 accepted 主张」）。

---

## 3. 全量（门禁通过后再做）

对 7 个已 publish 视频依次 `--no-pending` analyze → validate → render `--from-db` → publish。  
**不要**一次 analyze 全频道。

---

## 4. 红线

- `data/store.db` 前后 SHA 记入 HANDOFF
- 不 weaken `houchen_validator` / `houchen_quote`
- 日志不含 API key

---

## 5. 交付

| 动作 | 要求 |
|------|------|
| 报告 | `reviews/PR4_PROMPT_ALIGN_V3_REPORT_2026-08-25.md` |
| HANDOFF | accepted 数、样例 claim、Obsidian 路径 |
| INBOX | `WAIT_CURSOR` |
