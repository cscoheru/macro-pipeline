# Claude Code — Prompt 对齐 §9.3 + 单视频试跑

> **签发**：Cursor（2026-08-25）  
> **触发**：用户「对齐 prompt」  
> **前置**：`PR4_REAL_MODEL_EXPAND_ACCEPTANCE`（真模型 0 accepted）

---

## 用户摘要

已重写 `config/houchen_analysis_prompt.md`（v2）并 bump `PROMPT_VERSION=2026-08-25.1`；INPUT bundle 现含 `raw_caption_sha256`。请 **单视频试跑**，门禁：**≥1 real accepted claim** → render → publish。

---

## 0. 同步

```bash
cd /Users/kjonekong/macro-pipeline
git pull   # 或合并 Cursor 本地改动
python3 -m pytest scripts/test_houchen_analyzer.py scripts/test_houchen_prompt.py -q
```

---

## 1. 试跑视频（建议）

优先选较短、已成功 analyze 的：

`7DsxtHsOCzA`（20 rejected）或 `AWxr0xZwKII`（0 claim 行）

```bash
export PROVIDER=deepseek   # 与 houchen_analyze.env 一致

python3 scripts/houchen_pipeline.py analyze \
  --live-smoke-allow --provider "$PROVIDER" \
  --no-pending --video-id 7DsxtHsOCzA

python3 scripts/houchen_pipeline.py validate --live-smoke-allow --video-id 7DsxtHsOCzA
```

**门禁**：`validate` summary 中 `validated` ≥ 1（real accepted，非 fake 遗留）。

若仍 0：在 HANDOFF 记录 **R2/R5 拒因占比**（`sqlite3` 查最新 rejected claim_text），停等 Cursor 调 prompt。

---

## 2. 通过后：render + publish

需用 **accepted claims 填充 VideoPage**（从 DB 读 `claim` + `claim_source`，勿用空 claims）。

若尚无 `build_video_page_from_db`：在 kickoff 内实现最小 helper（`houchen_runner` 或 `houchen_render` 旁），或 `--from-json` 由脚本组装。

```bash
python3 scripts/houchen_pipeline.py render --kind video --page-key 7DsxtHsOCzA --apply ...
python3 scripts/houchen_pipeline.py publish --kind video --apply --operator-authorized --actor prompt-align-smoke
```

Obsidian 页应出现 **声明列表**（非「无 accepted 主张」）。

---

## 3. 全量（门禁通过后再做）

对 7 个已 publish 视频依次 `--no-pending` analyze → validate → render → publish。  
**不要**一次 analyze 全频道（费用 + 超时）。

---

## 4. 红线

- `data/store.db` 前后 SHA 记入 HANDOFF
- 不 weaken `houchen_validator` / `houchen_quote`
- 日志不含 API key

---

## 5. 交付

| 动作 | 要求 |
|------|------|
| 报告 | `reviews/PR4_PROMPT_ALIGN_REPORT_2026-08-25.md` |
| HANDOFF | accepted 数、样例 claim、Obsidian 路径 |
| INBOX | `WAIT_CURSOR` |
