# Claude Code — 拒做四项核验与下一步裁定

> **签发**：Cursor（2026-08-24 17:28）  
> **受众**：Claude Code；用户见 §用户裁定

---

## 用户摘要

| 项 | 结果 |
|----|------|
| 拒做 push main / --force / 部署 / 真模型 | **正确** — 不得执行 |
| 特性分支 tip | `0d0e2c4`（docs bundle）@ `feat/houchen-pr3-claim-extraction` |
| `main` | 本地仍 `aae7903`（未推 PR-3） |
| 远端 | `origin` = SSH；已有 `origin/feat/houchen-pr3-claim-extraction` |
| **推荐下一步** | **开 PR**（选项 1） |

---

## 1. Cursor 核验

```text
分支: feat/houchen-pr3-claim-extraction...origin/feat/houchen-pr3-claim-extraction
tip:  0d0e2c4 docs: PR-3 post-commit review bundle
main: aae7903
origin: git@github.com:cscoheru/macro-pipeline.git
core.sshCommand: ssh -i ~/.ssh/id_ed25519_github -o IdentitiesOnly=yes ...
远端 heads: feat/houchen-pr3-claim-extraction 存在
残留: ?? reviews/CC_BRANCH_FIX_VERIFIED_2026-08-24.md（可并入后续 docs 或随 PR 说明）
```

CC 对四项禁令的解释与项目约束一致。**不要**再提议 push main / force / deploy / live model，除非用户书面单开工单。

---

## 2. 选项执行工单

### 选项 1 — `gh pr create`（推荐；用户授权「开 PR」后）

```bash
cd /Users/kjonekong/macro-pipeline
git checkout feat/houchen-pr3-claim-extraction

# 可选：先提交残留核验文件
git add reviews/CC_BRANCH_FIX_VERIFIED_2026-08-24.md
git commit -m "$(cat <<'EOF'
docs: record BRANCH-FIX verification

EOF
)" && git push origin HEAD

gh pr create --base main --head feat/houchen-pr3-claim-extraction --title "feat: houchen PR-3 claim extraction and concept seeding" --body "$(cat <<'EOF'
## Summary
- Schema v3 + hard validator (brief §9.3) + fake-only analyze/validate/concept-seed
- Offline E2E; 314 scripts tests green; PR-1 red-line baseline unchanged
- Feature branch only; main remains PR-2 archive tip until merge

## Test plan
- [x] `python3 -m pytest scripts -q` → 314 passed
- [ ] Reviewer: `reviews/PR3_ACCEPTANCE_CURSOR_2026-08-24.md`
- [ ] Reviewer: do not merge with live-model or deploy steps

EOF
)"
```

回报 PR URL。**不要** merge，除非用户另授。

### 选项 2 — SSH → HTTPS 回退（仅用户授权「切回 HTTPS」）

```bash
git remote set-url origin https://github.com/cscoheru/macro-pipeline.git
git config --unset-all core.sshCommand   # 若仅本仓库设置
# 若是 --global，先 git config --global --get core.sshCommand 再确认是否 unset
git remote -v
git ls-remote --heads origin | head
```

**不要**改 `~/.ssh` 密钥文件。SSH 当前可用则**无必要**切换。

### 选项 3 — 等待

停止。

---

## 3. 用户裁定门

| 回复 | CC 动作 |
|------|---------|
| **开 PR** | 执行选项 1 |
| **开 PR（含 BRANCH-FIX 核验文件）** | 选项 1 + 先 commit 残留 |
| **切回 HTTPS** | 执行选项 2 |
| **暂缓** | 选项 3 |

---

## 4. 修订历史

| 时间 | 事件 |
|------|------|
| 2026-08-24 17:28 | 确认拒做四项正确；特性分支已在远端；等开 PR 授权 |
