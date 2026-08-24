# Claude Code ↔ Cursor 对接协议（常驻）

> **生效**：2026-08-24  
> **受众**：Claude Code（实现 Agent）  
> **用户角色**：仅在「用户裁定门」出现时决策；日常传话由本文件消除  
> **Cursor 角色**：审验、写下一步工单到 `reviews/`；不代写实现（除非用户改派）

---

## 0. 一句话

**你（CC）执行 → 把证据写入 `reviews/` → 停 → 等 Cursor 在 `reviews/` 更新下一工单。**  
不要等用户复述 Cursor 的话；用户只处理裁定门里的选择题。

---

## 1. 每回合开始（强制）

按顺序只读：

1. `reviews/CC_STANDING_ORDERS.md`（本文件）
2. `reviews/` 下**最新**的 `CC_*` / `*_ACCEPTANCE_*` / `*_VERIFIED_*`（按 mtime）
3. 若任务涉及 PR-N：对应 `PRN_DELIVERY` / `PRN_PLAN_AUDIT` / handoff 相关节

以**最新 Cursor 工单**为准；旧工单冲突时以日期更新的文件为准。

---

## 2. 工作循环

```text
读最新 reviews 工单
  → 执行允许的动作（实现 / 测试 / docs commit / 特性分支 push / 开 PR…）
  → 更新或新建 reviews/ 交付文件（事实 + 命令输出摘要 + 文件清单）
  → git：按工单要求 commit（特性分支）；push 仅当工单或用户明确授权
  → 停止并写出「等待 Cursor 审验」
  → 禁止自行开始下一阶段（PR-4 实现、真模型、merge、deploy）
```

### 2.1 完成后必须写入的交付物

每个工作包结束时，新建或更新：

`reviews/CC_HANDOFF_<YYYY-MM-DD>.md`（或当日已有则追加一节）

最少包含：

| 字段 | 内容 |
|------|------|
| 完成项 | 对照工单勾选 |
| 测试 | 命令 + 通过数 |
| 红线 | `store.db` SHA、`data/houchen/` 文件数（若相关） |
| Git | 分支、tip SHA、是否已 push、PR URL |
| 未做 | 明确列出 |
| 请 Cursor | 一句：请审验并写下一工单 |

---

## 3. 硬禁令（无用户书面授权则永不做）

- `git push` 到 `main` / `master`
- `git push --force` / `--force-with-lease` 到 main（任何 force 到共享分支）
- 部署、改 launchd/cron、装定时任务
- 真实模型调用（`anthropic` / `deepseek` / `minimax` 等非 `fake`）
- 全频道 live 分析 / 未授权联网 smoke
- 修改三份 Codex 基线文档正文、两份 DOCX
- 读写宏观 `data/store.db` 作为研究库写入目标
- 弱化测试、删断言、把失败改成 skip 关问题

当前默认 provider：**fake**；远程默认：特性分支 only。

---

## 4. Git 默认行为

| 场景 | 动作 |
|------|------|
| 实现 / 文档 | 在 `feat/…` 分支 commit |
| commit 后 | **仅当**最新工单写明「push 本特性分支」或用户本回合授权 → `git push -u origin HEAD` |
| 开 PR | 仅当工单或用户授权 → `gh pr create --base main --head <feat>` |
| merge PR | **仅用户**授权 |
| 残留 reviews | 可 docs commit 到当前 feat 分支；不要单独污染 main |

`origin`：以仓库当前 `git remote get-url origin` 为准（SSH 或 HTTPS 均可；不要擅自改 URL，除非工单「切回 HTTPS」）。

---

## 5. 用户裁定门（只有这些才打断用户）

需要用户在 **Cursor 会话或 CC 会话** 回复原句之一时，**停止实现**并提问（可引用本表）：

| 用户原句 | 含义 |
|----------|------|
| **开 PR** | `gh pr create --base main --head feat/houchen-pr3-claim-extraction`（或工单指定 head） |
| **合并 PR** | merge（方式按工单） |
| **push 特性分支** | `git push -u origin HEAD`（当前 feat） |
| **push main** | 仅空仓/明示 bootstrap；默认拒绝 |
| **切回 HTTPS** | remote URL + 按需 unset `core.sshCommand` |
| **授权 live smoke** | 独立 temp root、subtitle-only |
| **授权真模型** | 非 fake provider + env |
| **启动 PR-N 实现** | 须已有计划 + Cursor `PRN_PLAN_AUDIT` 批准 |
| **暂缓** | 停止 |

**不要**让用户转发 Cursor 的长审验文；用户只需在 Cursor 里裁定，或把上表短词发给你。

---

## 6. Cursor 如何给你下一指令

Cursor 会更新 `reviews/`（例如 `CC_NEXT_*.md`、`PRN_ACCEPTANCE_*.md`）。  
你的触发条件：**看到新工单文件或既有文件新增「§工单 / §下一步」** → 执行 → 写 `CC_HANDOFF_*` → 停。

若 Cursor 与用户口头不一致：**以 `reviews/` 书面工单为准**；冲突则停并请用户裁定。

---

## 7. 当前积压（2026-08-24 17:34 快照）

| 状态 | 项 |
|------|-----|
| ✅ | PR-3 在 `feat/houchen-pr3-claim-extraction`（tip 含 docs bundle）；已 push 特性分支 |
| ✅ | `main` @ `aae7903`（本地） |
| ⏳ | **等用户：开 PR**（推荐） |
| ⏳ | 残留 `reviews/CC_BRANCH_FIX_VERIFIED_2026-08-24.md` 等可随 PR 前 docs commit |
| 🚫 | push main / force / deploy / 真模型 |

用户一旦说 **开 PR**，执行本文件 §5 + 详见 `reviews/CC_NEXT_AFTER_PUSH_REFUSAL_2026-08-24.md` §2 选项 1。

---

## 8. 修订历史

| 时间 | 事件 |
|------|------|
| 2026-08-24 | 初版：消除用户传声筒；CC 读写 reviews 闭环 |
