# Claude Code — 概念页增量 Refresh（P4）

> **签发**：Cursor（2026-08-25）  
> **触发**：用户「概念页随 claim 增量 refresh」  
> **不问用户**；交卷 → `WAIT_CURSOR`

---

## 目标

240 accepted claims 后，**所有挂 accepted claim 的概念** re-render + publish（当前约 **63** 概念，此前只发 18 页）。

---

## 0. 同步

```bash
cd /Users/kjonekong/macro-pipeline
git pull
STORE=$(shasum -a 256 data/store.db | awk '{print $1}')
echo "$STORE"   # 4a8e409b…
```

---

## 1. 列出待刷新概念

```bash
python3 - <<'PY'
import sys; sys.path.insert(0,"lib")
import houchen_store
c=houchen_store.connect()
rows=c.execute("""
  SELECT c.concept_id, c.canonical_name,
    (SELECT COUNT(*) FROM claim_concept cc
     JOIN claim cl ON cl.claim_id=cc.claim_id AND cl.status='accepted'
     WHERE cc.concept_id=c.concept_id) AS acc_n
  FROM concept c
  WHERE EXISTS (
    SELECT 1 FROM claim_concept cc
    JOIN claim cl ON cl.claim_id=cc.claim_id AND cl.status='accepted'
    WHERE cc.concept_id=c.concept_id
  )
  ORDER BY acc_n DESC, c.canonical_name
""").fetchall()
print(len(rows))
for r in rows: print(r[0], r[2], r[1][:40] if r[1] else "")
c.close()
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
  --kind concept --apply --operator-authorized --actor concept-incremental-p4
```

---

## 2. 门禁

| 项 | 标准 |
|----|------|
| render | ≥60 概念（与 SQL 计数接近） |
| publish | `published` ≥60；0 failed |
| SHA | 抽 3 页 vault_sha256 == render_sha256 |
| Obsidian | 抽 1 页 GET 200 |
| store.db | SHA == before |
| 报告 | 只写 concept_id 前12、acc_n、新旧 SHA 是否变；**不贴 claim 正文** |

---

## 3. 交付

- `reviews/CONCEPT_INCREMENTAL_REFRESH_REPORT_2026-08-25.md`
- HANDOFF 追加
- INBOX → `WAIT_CURSOR`
- 无代码改动可不 commit；有改动则 push

---

## 不做

- `promote_to_canonical`
- 新 analyze / ASR / WPS
