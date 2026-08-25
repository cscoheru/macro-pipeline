# Claude Code — 字幕 P1 + 扩竖切 + Macro 人工 Review

> **签发**：Cursor（2026-08-25）  
> **触发**：用户「全量字幕计划，然后扩视频竖切 及 macro-bridge 人工 review」  
> **计划**：`docs/plans/full-caption-corpus.md`（已写；本工单执行 **P1 + P2 + PR-5.1 review**）  
> **不问用户**；交卷 → `WAIT_CURSOR`

---

## 上下文纪律

- 报告：**仅** video_id、claim_id、candidate_id、计数、SHA、outcome 枚举  
- **禁止**贴完整字幕/claim 正文/敏感 title 长文  
- 过滤报错 → 新会话 + sqlite 聚合  
- 跳过已知：`f_jd_j3eEuE`、`mg_BuWqSL9A`

---

## 0. 同步

```bash
cd /Users/kjonekong/macro-pipeline
git pull
STORE=$(shasum -a 256 data/store.db | awk '{print $1}')
echo "$STORE"   # expect 4a8e409b…
```

---

## A — 字幕 P1（轨 A，必做）

对照 `docs/plans/full-caption-corpus.md` §轨 A。

```bash
# 可选刷新编目
python3 scripts/houchen_pipeline.py catalog --live-smoke-allow

# 循环直至 pending=0（--limit 20 每轮）
python3 scripts/houchen_pipeline.py fetch-captions --pending --limit 20 --live-smoke-allow
python3 scripts/houchen_pipeline.py normalize --pending --limit 20

python3 scripts/houchen_pipeline.py coverage --markdown \
  | tee reviews/HOUCHEN_CAPTION_COVERAGE_2026-08-25-P1.md
python3 scripts/houchen_pipeline.py status
```

**门禁:** `caption pending=0`（terminal missing 允许）。  
**禁止:** 本阶段 analyze。

---

## B — 扩视频竖切（P2，必做）

**目标:** ≥**25** 视频有 accepted claim；accepted 合计尽量 ≥**120**（达不到则记实际数，不卡交卷）。

### B1. 待分析池

有 `transcript_version.status=ok` 且 **无** accepted claim 的视频（`vtt_json3_v1` 优先；含 A 阶段新建）。

```bash
python3 - <<'PY'
import sys; sys.path.insert(0,"lib")
import houchen_store
c=houchen_store.connect()
rows=c.execute("""
  SELECT v.video_id FROM video v
  WHERE EXISTS (
    SELECT 1 FROM transcript_version tv
    WHERE tv.video_id=v.video_id AND tv.status='ok'
  )
  AND NOT EXISTS (
    SELECT 1 FROM claim cl WHERE cl.video_id=v.video_id AND cl.status='accepted'
  )
  ORDER BY v.video_id
""").fetchall()
print(len(rows))
for r in rows: print(r[0])
c.close()
PY
```

### B2. 逐视频竖切

对池中视频（**上限 25 支/本工单**，超出记入「下一批」）：

```bash
VID=...
python3 scripts/houchen_pipeline.py analyze \
  --no-pending --provider deepseek --video-id "$VID" --live-smoke-allow
python3 scripts/houchen_pipeline.py validate --video-id "$VID"
python3 scripts/houchen_pipeline.py render --kind video --page-key "$VID" --from-db
```

单支 accepted=0：记拒因 rule id **计数**，继续下一支。

### B3. Publish

```bash
python3 scripts/houchen_pipeline.py publish \
  --kind video --apply --operator-authorized --actor corpus-expand-p2
```

**禁止:** 全 129 analyze；单批 >25 新 analyze。

---

## C — Macro-bridge 人工 Review（PR-5.1，必做）

现状：~347 `macro_link_candidate`，`reviewed=0`。实现 review 工作流 + **试点人工决议**。

### C1. 代码（≤4 文件改动）

在 `lib/macro_bridge.py` + `houchen_pipeline.py` + `test_macro_bridge.py`：

| CLI | 行为 |
|-----|------|
| `macro-bridge --review-queue [--limit N]` | 导出待审队列（stdout JSON 或写 `reviews/MACRO_BRIDGE_REVIEW_QUEUE_2026-08-25.md`） |
| `macro-bridge --mark-reviewed ID [--relation REL]` | `reviewed=1`；可选改 relation |
| `macro-bridge --import-reviewed [--limit N]` | 对 `reviewed=1` 且未导入者调 `import_to_evaluation` |
| （可选）`scan` dedupe | 同 `(claim_id, macro_source, macro_series, macro_period)` 不重复 INSERT |

队列 Markdown 格式（每条）：

```text
- candidate_id | claim_id | macro_source/series | relation | reviewed?
```

claim 摘要 **≤80 字**；勿贴长文。

### C2. 试点 review（人工决议）

- 从队列选 **15–25** 条（优先：不同 `claim_id`、宏观关键词 CPI/通胀/GDP/利率 相关）  
- 对每条写明决议：`confirm contextualizes` / `reject` / `upgrade supports|challenges`（仅当有充分理由）  
- 写入 `reviews/MACRO_BRIDGE_REVIEW_DECISIONS_2026-08-25.jsonl`（机器可读，无长引文）  
- `--mark-reviewed` 应用决议 → `--import-reviewed` 导入 evaluation  

**门禁:** ≥10 条 `reviewed=1` 且 ≥10 条 `evaluation`（`evaluator=macro_bridge`）；`store.db` SHA 不变。

### C3. 测试

`pytest scripts/test_macro_bridge.py -q` 全绿；新增 review/import 测试。

---

## D. 交付

| 文件 | 内容 |
|------|------|
| `docs/plans/full-caption-corpus.md` | 已在 main（若本地无则 commit） |
| `reviews/HOUCHEN_CAPTION_COVERAGE_2026-08-25-P1.md` | P1 coverage |
| `reviews/CORPUS_EXPAND_REPORT_2026-08-25.md` | A/B/C 摘要 + 视频/claim 计数 |
| `reviews/MACRO_BRIDGE_REVIEW_QUEUE_2026-08-25.md` | 队列 |
| `reviews/MACRO_BRIDGE_REVIEW_DECISIONS_2026-08-25.jsonl` | 决议 |
| `reviews/MACRO_BRIDGE_REVIEW_REPORT_2026-08-25.md` | reviewed/import 计数 |
| HANDOFF 追加 | |
| INBOX | `WAIT_CURSOR` |

代码 commit + **push origin main**（用户已要收 PR-5 惯例）。

---

## 红线

- `store.db` SHA before == after  
- 不 whisper / 不 `asr_transcribe.py`  
- 不弱化 validator  
- 轨 B（用户 WPS 下一批）**本工单不做** — 留给 P3 用户导入后再开
