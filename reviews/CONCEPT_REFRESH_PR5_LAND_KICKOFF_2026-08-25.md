# Claude Code — 概念页刷新 + 收 PR-5

> **签发**：Cursor（2026-08-25）  
> **触发**：用户「概念页刷新 并收 PR-5」  
> **不问用户**；交卷 → `WAIT_CURSOR`

---

## 用户摘要

1. **概念页刷新**：WPS 后 accepted 已至 ~75；重 render + publish 概念页（含新挂链）。  
2. **收 PR-5**：把已实现的 macro-bridge **落库 git**、复跑 scan/verify、写 acceptance；关 PR-5。

---

## 0. 同步与红线

```bash
cd /Users/kjonekong/macro-pipeline
git pull
STORE_BEFORE=$(shasum -a 256 data/store.db | awk '{print $1}')
echo "$STORE_BEFORE"   # expect 4a8e409b…
```

| 红线 | |
|------|--|
| `store.db` SHA 前后不变 | |
| 不 `promote_to_canonical` | |
| 不全库 analyze / 不下音频 / 不跑 whisper | |
| **勿** `git add scripts/asr_transcribe.py`（废弃机转写） | |
| 报告勿贴 claim/转写正文 | |

---

## A. 概念页刷新（必做）

```bash
python3 - <<'PY'
import sys; sys.path.insert(0,"lib")
import houchen_store, houchen_runner
c=houchen_store.connect()
ids=houchen_runner.list_concepts_for_research_pages(c, limit=12)
print("\n".join(ids)); c.close()
PY
```

对每个 `CONCEPT_ID`：

```bash
python3 scripts/houchen_pipeline.py render \
  --kind concept --page-key "$CONCEPT_ID" --from-db
```

然后：

```bash
python3 scripts/houchen_pipeline.py publish \
  --kind concept --apply --operator-authorized --actor concept-refresh-wps
```

**门禁**

- ≥6 概念页 `publish_record.status=published`
- 抽 1 页 Obsidian GET 200；`vault_sha256 == render_sha256`
- 报告写：concept_id 前 12、accepted_links 数、新旧 SHA 是否变化（可不贴正文）

---

## B. 收 PR-5（必做）

### B1. 验证

```bash
python3 -m pytest scripts/test_macro_bridge.py -q
python3 scripts/houchen_pipeline.py macro-bridge --verify-sha "$STORE_BEFORE"
python3 scripts/houchen_pipeline.py macro-bridge --scan
# 可选：export 到 /tmp，勿提交 JSONL
python3 scripts/houchen_pipeline.py macro-bridge --export /tmp/macro_links_pr5.jsonl
```

记录：claims_scanned、candidates、relation 分布、SHA match。

### B2. Git 落库（仅 PR-5 相关）

**纳入**：

- `lib/macro_bridge.py`
- `config/macro_bridge_keywords.yaml`
- `scripts/test_macro_bridge.py`
- `scripts/houchen_pipeline.py`（已含 macro-bridge；若同文件含 `import-transcript`，**一并提交**——已上线能力，勿拆坏）
- `lib/houchen_import_transcript.py` + `scripts/test_import_transcript.py`（同竖切依赖，可同 commit 或紧随第二 commit）
- `reviews/PR5_IMPL_REPORT_2026-08-25.md`
- 更新 `docs/plans/pr5-macro-bridge.md` 顶部 `Status: Implemented (landed YYYY-MM-DD)`

**排除**：`scripts/asr_transcribe.py`；音频/segments；任意 `*.jsonl` 导出；`.env`

Commit 风格（conventional，why）：

```text
feat(houchen): land PR-5 macro-bridge (readonly store, candidate links)

Close brief §16 PR-5: keyword scan + JSONL export; store.db SHA frozen.
```

若 import 分拆第二 commit：`feat(houchen): WPS import-transcript path for stream pilots`

**push `origin main`**（本仓库协作惯例；用户已要「收」）。

### B3. Acceptance

写 `reviews/PR5_ACCEPTANCE_2026-08-25.md`：

| 项 | 标准 |
|----|------|
| tests | test_macro_bridge 全绿 |
| store SHA | == before |
| scan | 有 candidates；零写 store |
| git | PR-5 文件在 main |
| 概念刷新 | A 节门禁 |

另写 `reviews/CONCEPT_REFRESH_REPORT_2026-08-25.md`（可短）。

---

## C. INBOX / HANDOFF

- HANDOFF 追加 A+B 摘要  
- `CC_INBOX` → `WAIT_CURSOR`

---

## 不做

- 全频道 analyze / 新 ASR / 弱化 validator  
- `import_to_evaluation` 自动写回（仍需 reviewed=1）  
- 修产品文案 / 重开 PR-4 范围争论  
