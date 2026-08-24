# Claude Code — Git remote 与提交后同步规范

> **签发**：Cursor（2026-08-24）
> **远程**：https://github.com/cscoheru/macro-pipeline.git
> **受众**：Claude Code；用户见 §用户摘要

---

## 用户摘要

| 项 | 状态 |
|----|------|
| GitHub 仓库 | 已存在（空仓）：https://github.com/cscoheru/macro-pipeline |
| 本地 `origin` | 由 Cursor 配置为上述 URL |
| 首次 push | 依赖本机 `gh`/`git` 凭证（见 §3） |
| CC 职责 | **每次 commit 后**按 §2 推送当前分支；**禁止** force-push `main` |

---

## 1. Remote 配置（一次性）

```bash
cd /Users/kjonekong/macro-pipeline

# 若尚无 origin：
git remote add origin https://github.com/cscoheru/macro-pipeline.git

# 若已有错误 URL：
git remote set-url origin https://github.com/cscoheru/macro-pipeline.git

git remote -v
# origin  https://github.com/cscoheru/macro-pipeline.git (fetch)
# origin  https://github.com/cscoheru/macro-pipeline.git (push)
```

**不要**另建第二 remote 名（除非用户明确要求 `upstream`）。Cursor / CC 统一用 `origin`。

---

## 2. 每次 commit 后的强制同步流程（CC 默认执行）

用户授权 commit 后，**同一回合内**必须：

```bash
# A. 确认当前分支（禁止在不知情时推 main 的非常规 tip）
git branch --show-current
git status -sb

# B. 推送当前分支（首次加 -u）
git push -u origin HEAD

# C. 若当前在 main 且用户未明确说「push main」：
#    → 先 BRANCH-FIX（见 CC_POST_COMMIT_PR3）再 push 特性分支；
#    → 或询问用户，不得擅自 push main。
```

### 分支策略（ongoing）

| 场景 | 动作 |
|------|------|
| 新功能 / PR-N | `feat/houchen-prN-…` 上 commit → `git push -u origin HEAD` → 用户授权后 `gh pr create` |
| 文档/reviews 小修 | 同特性分支或 `docs/…` 分支；勿堆在 main |
| Hotfix | `fix/…` 分支；PR 合入 main |

**硬规则**：

- 永不 `git push --force` / `--force-with-lease` 到 `main`（除非用户书面授权）
- 永不 `--no-verify` 跳过 hook（除非用户明确要求）
- push 失败（401/403）→ 停止并报告；**不要**反复尝试换 URL 或改凭据文件

---

## 3. 凭证（本机阻塞项 — 需用户处理）

Cursor 实测（2026-08-24）：

```text
gh auth status → token in keyring is invalid (HTTP 401)
```

用户需在本机执行（交互式，CC/Cursor **不能**代填）：

```bash
gh auth login -h github.com
# 或确保 git 对 github.com 有可用 HTTPS/SSH 凭据
```

验证：

```bash
gh repo view cscoheru/macro-pipeline
git ls-remote origin
```

空仓首次推送：

```bash
# 推荐：特性分支（若已 BRANCH-FIX）
git push -u origin feat/houchen-pr3-claim-extraction

# 或空仓引导：用户明确授权「push main」时
git push -u origin main
```

GitHub UI 显示仓库已存在且为空：https://github.com/cscoheru/macro-pipeline — **无需再 create**；只需 push 填内容。

---

## 4. 与 PR-3 提交卫生的关系

当前本地 `main` = `58dea6c`（PR-3）。空仓首次同步前，**强烈建议**用户先授权：

> **移到特性分支并恢复 main**

顺序：

1. BRANCH-FIX（`CC_POST_COMMIT_PR3_2026-08-24.md` §3）
2. `git push -u origin feat/houchen-pr3-claim-extraction`
3. （可选）`git push -u origin main` 仅推 `aae7903` 基线 — 或等 PR merge

若用户说 **「保留 main 并 push main」**：允许一次性 `git push -u origin main`（空仓 bootstrap），但后续新工作仍须特性分支。

---

## 5. 交付检查清单（CC 每个 push 回合）

- [ ] `git remote get-url origin` == `https://github.com/cscoheru/macro-pipeline.git`
- [ ] commit 已完成且 `git status` 对应该提交干净（或仅说明残留）
- [ ] `git push` 成功；输出含 remote URL / branch
- [ ] 向用户回报：commit SHA、分支名、是否已 push、PR URL（若创建）

---

## 6. 修订历史

| 时间 | 事件 |
|------|------|
| 2026-08-24 | 指定 origin URL；CC 提交后自动 push 规范；凭证需用户 `gh auth login` |
