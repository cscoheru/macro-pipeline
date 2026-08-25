# Claude Code — 关闭 PR-4 退出条件（概念页）+ 竖切补到 8–12

> **签发**：Cursor（2026-08-25）  
> **触发**：用户「按计划推进、交给 CC、无必要不找用户」  
> **对照**：brief §16 PR-3/PR-4 退出；§26 全量字幕/PR-5/ASR **本工单不做**

---

## 用户摘要

关 brief **PR-4 退出**（≥1 张可用概念页）并尽量把分析竖切补到 **8–12** 视频。Cursor 已补 `build_concept_page_from_db` + `render --kind concept --from-db`。**不要**改产品方向、**不要**弱化 validator、**不要**开 PR-5/ASR/全频道 637。

完成后写报告，INBOX → `WAIT_CURSOR`。

---

## 0. 同步

```bash
cd /Users/kjonekong/macro-pipeline
git pull
python3 -m pytest scripts/test_houchen_render.py scripts/test_houchen_publisher.py -q
```

红线：记 `data/store.db` SHA before/after（应无漂移）。

---

## 1. 概念页（PR-4 退出，必做）

选出最多 **6** 个有 `concept_source`、优先挂 accepted claim 的概念（可用下方 SQL，或 `houchen_runner.list_concepts_for_research_pages`）：

```bash
python3 - <<'PY'
import sys; sys.path.insert(0,"lib")
import houchen_store, houchen_runner
c=houchen_store.connect()
ids=houchen_runner.list_concepts_for_research_pages(c, limit=6)
print("\n".join(ids)); c.close()
PY
```

对每个 `CONCEPT_ID`：

```bash
python3 scripts/houchen_pipeline.py render \
  --kind concept --page-key "$CONCEPT_ID" --from-db

python3 scripts/houchen_pipeline.py publish \
  --kind concept --page-id "rp_concept_${CONCEPT_ID}" \
  --apply --operator-authorized --actor pr4-concept-exit
```

若 `--page-id` 不便：`publish --kind concept --apply --operator-authorized --actor pr4-concept-exit`（会发该 kind 全部已 render 页）。

**门禁**：

- Obsidian 至少 **1** 页：`Research/世界苦茶/concept/<concept_id>.md`
- 页内有标题/定义，且 **Speaker uses** 或 Canonical definition **非空**
- `vault_sha256 == render_sha256`

**禁止**：`promote_to_canonical`（需人类裁定；本工单保持 `proposed`）。

---

## 2. 竖切补视频（尽量做到 8–12）

当前：9 条 raw_caption，7 条已成功 analyze。

### 2a. 已有字幕未分析的

对仍有 `ok` transcript、未成功 analyze 的视频（若有）依次：

```bash
python3 scripts/houchen_pipeline.py analyze --no-pending --provider deepseek --video-id "$VID"
python3 scripts/houchen_pipeline.py validate --video-id "$VID"
python3 scripts/houchen_pipeline.py render --kind video --page-key "$VID" --from-db
```

已知可能永久失败：`f_jd_j3eEuE`（content_filter）、`mg_BuWqSL9A`（HTTP 400）— 跳过并记入报告。

### 2b. 再抓 3–5 条分析线字幕

```bash
python3 scripts/houchen_pipeline.py fetch-captions --pending --limit 5 --live-smoke-allow
python3 scripts/houchen_pipeline.py normalize --pending --limit 5
```

对新建 transcript 的视频：analyze → validate → render（同上）。目标：**成功 validate 且 accepted≥1 的视频数 ≥ 8**（能到 12 更好；单视频超时/费用过大则停在 ≥8）。

最后：

```bash
python3 scripts/houchen_pipeline.py publish \
  --kind video --apply --operator-authorized --actor pr4-vertical-topup
```

---

## 3. 红线

- 不改 `houchen_validator` / `houchen_quote`
- 不写 `data/store.db`
- 不做全频道 637 analyze、不做 PR-5、不做 ASR
- 日志不含 API key
- 不 push（除非用户另说）；本地 commit 仅当工单内改了代码且逻辑完整

---

## 4. 交付

| 文件 | 内容 |
|------|------|
| `reviews/PR4_CONCEPT_EXIT_REPORT_2026-08-25.md` | 概念页路径、样例、视频数、accepted 合计、失败 ID、store.db SHA |
| `reviews/CC_HANDOFF_2026-08-24.md` | 追加本节摘要 |
| `reviews/CC_INBOX.md` | `STATUS=WAIT_CURSOR` |

---

## 5. 完成后 Cursor 将审验

对照 brief §16：概念页可用 + 竖切规模。§26（全量字幕 / PR-5 / ASR）仍留给下一工单，**本回合不要问用户**。
