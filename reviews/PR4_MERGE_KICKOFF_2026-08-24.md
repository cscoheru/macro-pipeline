# Claude Code — 合并 PR #2

> **签发**：Cursor（2026-08-24）  
> **前置**：用户已说「合并 PR」；`reviews/PR4_GITHUB_REVIEW_2026-08-24.md` PASS  
> **PR**：https://github.com/cscoheru/macro-pipeline/pull/2

---

## 用户摘要

合并 PR #2 到 `main`。做完写 HANDOFF，INBOX 改 `WAIT_CURSOR`。不部署、不 live smoke。

---

## 1. 合并前自检

```bash
git fetch origin
git checkout feat/houchen-pr4-fts-publish
python3 -m pytest scripts -q    # 384
find data/houchen -type f | wc -l  # 0
```

---

## 2. 合并

```bash
gh pr merge 2 --merge --delete-branch
# 或用户偏好 squash 时：gh pr merge 2 --squash --delete-branch
```

默认 **merge commit**（保留 4 commit 历史；与 PR-3 一致）。

---

## 3. 本地同步

```bash
git checkout main
git pull origin main
python3 -m pytest scripts -q
```

---

## 4. 交付

| 动作 | 要求 |
|------|------|
| HANDOFF | 追加 §PR-4 Merge：`main` tip SHA、测试数 |
| INBOX | `WAIT_CURSOR` 或 `WAIT_USER`（若等 live smoke 裁定） |
| `PR1_HANDOFF.md` | §12 注明 merged @ main tip |
| 禁止 | force push、改 store.db、真模型 |

---

## 5. 合并后

- 可读研究成果仍无 — 需用户授权 `PR4_LIVE_SMOKE_KICKOFF`
- 可选：把 untracked `reviews/PR1_GITHUB_REVIEW_*` / `PR3_MERGED_*` 单独 docs commit（非必须）
