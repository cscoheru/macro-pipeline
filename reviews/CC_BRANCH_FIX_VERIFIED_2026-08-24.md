# Claude Code — BRANCH-FIX 完成核验与下一步

> **签发**：Cursor（2026-08-24 17:07）  
> **受众**：Claude Code；用户见 §用户裁定

---

## 用户摘要

| 项 | 结果 |
|----|------|
| 特性分支 | `feat/houchen-pr3-claim-extraction` @ `58dea6c` ✅ |
| `main` | `aae7903` ✅ |
| 测试 | 314 passed ✅ |
| Push | 未推 ✅ |
| 建议 1（docs commit） | **批准** — 用户确认后执行 |
| 建议 2（push 特性分支） | **批准流程** — **须另授**「push 特性分支」 |

---

## 1. Cursor 核验（已通过）

```text
当前分支: feat/houchen-pr3-claim-extraction
tip:       58dea6c
main:      aae7903
origin:    https://github.com/cscoheru/macro-pipeline.git
残留:
  M  reviews/COMMIT_VERIFIED_2026-08-24.md
  ?? reviews/CC_GIT_REMOTE_AND_SYNC_2026-08-24.md
  ?? reviews/CC_POST_COMMIT_PR3_2026-08-24.md
  ?? reviews/PR3_PLAN_AUDIT_2026-08-24.md
pytest scripts -q → 314 passed
```

BRANCH-FIX 符合 `CC_POST_COMMIT_PR3` §3。

---

## 2. 工单 DOCS-BUNDLE（用户确认「docs commit」后执行）

仅在 `feat/houchen-pr3-claim-extraction` 上：

```bash
cd /Users/kjonekong/macro-pipeline
git checkout feat/houchen-pr3-claim-extraction

git add \
  reviews/COMMIT_VERIFIED_2026-08-24.md \
  reviews/CC_GIT_REMOTE_AND_SYNC_2026-08-24.md \
  reviews/CC_POST_COMMIT_PR3_2026-08-24.md \
  reviews/PR3_PLAN_AUDIT_2026-08-24.md

# 若 CC_STATUS / 其它 reviews 也在工作区，一并只加 reviews/ 下相关文件；禁止 data/

git commit -m "$(cat <<'EOF'
docs: PR-3 post-commit review bundle

Archive plan audit, git remote sync SOP, and post-commit branch-hygiene notes
on the PR-3 feature branch after moving tip off main.
EOF
)"

git status -sb
git log -2 --oneline
```

**不要** push，除非用户本回合另授。

---

## 3. 工单 PUSH-FEAT（仅用户说「push 特性分支」时）

前置：`gh auth` / 网络可用；`git remote get-url origin` 正确。

```bash
git checkout feat/houchen-pr3-claim-extraction
git push -u origin feat/houchen-pr3-claim-extraction
```

禁止：`push main`、`--force`、部署、真模型。

成功后回报：远程 URL、分支、tip SHA。若用户再授「开 PR」，用 `gh pr create` 指向 `main`。

---

## 4. 用户裁定门

| 回复 | CC 动作 |
|------|---------|
| **docs commit** | 执行 §2 |
| **push 特性分支** | 执行 §3（建议先 docs commit） |
| **docs commit + push 特性分支** | §2 → §3 |
| **暂缓** | 停止 |

---

## 5. 修订历史

| 时间 | 事件 |
|------|------|
| 2026-08-24 17:07 | BRANCH-FIX 核验 PASS；批准 docs bundle / 待授 push |
