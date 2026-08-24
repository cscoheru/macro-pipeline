# Claude Code ↔ Cursor 对接协议（常驻）

> **生效**：2026-08-24（修订：主动轮询）  
> **受众**：Claude Code  
> **核心修复**：你**禁止**空等用户说「去看 reviews」。每回合开场必须自己扫盘。

---

## 0. 反传声筒铁律

1. **用户不是邮差。** Cursor 的下一步只写在 `reviews/`；你自己读。
2. **每回合第一条工具调用**必须是读 inbox + standing orders（见 §1），**早于**向用户提问「做什么」。
3. 若 inbox 有未完成工单：**直接执行**，不要问「要不要做」。
4. 只有 §5「用户裁定门」才向用户提问；其余停顿对象是 **Cursor（via HANDOFF）**，不是用户。
5. 用户若只发「？」「在吗」「进度」→ 你回复一句状态，并**立刻**再扫 `reviews/` 继续可执行工单。

---

## 1. 每回合启动协议（强制，不可跳过）

按顺序执行（可用一次 shell 合并）：

```bash
# A. 读 inbox（单一指针）
cat reviews/CC_INBOX.md

# B. 列出 reviews 近 24h 变更
ls -lt reviews/ | head -25

# C. 读本文件 + inbox 指向的工单全文
```

然后：

| 条件 | 动作 |
|------|------|
| `CC_INBOX.md` 状态 = **DO** | 执行「当前工单」路径；不问用户 |
| 状态 = **WAIT_USER** | 只问裁定门短词；不闲聊 |
| 状态 = **WAIT_CURSOR** | 写/更新 HANDOFF；告诉用户「已交 Cursor」；**不要编造下一阶段** |
| inbox 与最新 `*_KICKOFF_*` / `*_IMPL_*` 不一致 | **以更新的 kickoff/impl 为准**，并在 HANDOFF 注明 |

**禁止**：开场就问「你希望我做什么？」——先扫盘。

---

## 2. 工作循环

```text
§1 扫盘
  → 有 DO 工单：执行到底（或到硬禁令/裁定门）
  → 写 reviews/CC_HANDOFF_YYYY-MM-DD.md（或追加）
  → 若工单要求：更新 CC_INBOX.md 状态为 WAIT_CURSOR
  → 停止编码；下一动作留给 Cursor 改 inbox
```

### 2.1 HANDOFF 最低字段

完成项｜测试命令+通过数｜红线 SHA｜分支+tip｜是否 push｜未做｜请 Cursor 一句

### 2.2 你如何「呼叫」Cursor

- 不依赖用户转发。
- 更新 `CC_HANDOFF_*.md` + 把 `CC_INBOX.md` 设为 `WAIT_CURSOR`。
- Cursor 会主动读；用户只需在 Cursor 会话里偶尔出现。

---

## 3. 硬禁令（无书面授权永不做）

push main｜force 共享分支｜部署｜真模型｜未授权 live｜改 Codex 基线/DOCX｜写宏观 store.db｜弱化测试

默认：**fake** provider；push **仅**特性分支且需工单/用户授权。

---

## 4. Git 默认

| 场景 | 动作 |
|------|------|
| 实现 | `feat/…` commit |
| push | 仅工单写明或用户「push 特性分支」 |
| 开/合并 PR | 用户裁定门短词 |
| origin URL | 勿擅自改 |

---

## 5. 用户裁定门（唯一可问用户的内容）

| 原句 | 含义 |
|------|------|
| 开 PR / 合并 PR | gh 或说明网页 |
| push 特性分支 | `git push -u origin HEAD` |
| 启动 PR-N 实现 | 须有 AUDIT 批准 |
| 授权真模型 / live smoke | 另开工单 |
| 暂缓 | 停并把 inbox→WAIT_USER |

不要请用户「把 Cursor 的审验贴过来」。

---

## 6. Cursor 职责（给你对齐预期）

Cursor 会：

1. 更新 `reviews/CC_INBOX.md`（状态 + 工单路径）
2. 写 `*_KICKOFF_*` / `*_AUDIT_*` / `*_ACCEPTANCE_*`
3. **主动**看 HANDOFF / 分支进度（不靠用户催）

你与 Cursor 的汇合点 = **`reviews/` 文件系统**，不是用户聊天。

---

## 7. 当前积压（以 CC_INBOX 为准；此处备份）

见 `reviews/CC_INBOX.md`。备份快照 2026-08-24 18:03：

- **DO**：`reviews/PR4_IMPL_KICKOFF_2026-08-24.md`

---

## 8. 修订历史

| 时间 | 事件 |
|------|------|
| 2026-08-24 | 初版 |
| 2026-08-24 18:03 | 强制主动扫盘；新增 CC_INBOX 指针 |
