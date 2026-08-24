# CC/Cursor Handoff — 开 PR（2026-08-24）

## 完成

| 项 | 结果 |
|----|------|
| docs commit | `126c16b` standing orders + branch-fix notes |
| push feat | `origin/feat/houchen-pr3-claim-extraction` @ `126c16b` |
| bootstrap `origin/main` | `aae7903`（仅 PR-2 归档 tip；**不含** PR-3） |
| `gh pr create` | **失败**：`gh` keyring token HTTP 401 |

## 未完成（需用户 30 秒）

本机执行其一：

```bash
# A. 修复 gh 后创建
gh auth login -h github.com
cd ~/macro-pipeline
gh pr create --base main --head feat/houchen-pr3-claim-extraction \
  --title "feat: houchen PR-3 claim extraction and concept seeding" \
  --body-file - <<'EOF'
## Summary
- Schema v3 + hard validator + fake-only analyze/validate/concept-seed
- 314 tests; red-line store.db 52c12c82… unchanged until merge

## Test plan
- [x] pytest scripts -q → 314
- [ ] reviews/PR3_ACCEPTANCE_CURSOR_2026-08-24.md
EOF
```

或浏览器打开（一键开 PR）：

https://github.com/cscoheru/macro-pipeline/compare/main...feat/houchen-pr3-claim-extraction?expand=1

## 请 Cursor

用户贴出 PR URL 后，做 PR 审验工单；**勿 merge** 除非用户说「合并 PR」。

## 禁令仍生效

push --force、部署、真模型、未经授权 merge。

---

## §B — PR-4 计划交付（Plan-First；未写实现）

> 工单：`reviews/PR4_PLAN_KICKOFF_2026-08-24.md`（Cursor 2026-08-24 17:53）
> 用户授权：「执行 reviews/PR4_PLAN_KICKOFF_2026-08-24.md，只交计划，不写实现」

| 项 | 结果 |
|---|---|
| 计划文件 | `docs/plans/pr4-obsidian-research-map.md`（**NEW**，14 节 / 350+ 行） |
| 分支 | `feat/houchen-pr4-plan`（基于 `main@47e4de3`） |
| 实现代码 | **0**（仅 markdown 计划 + handoff） |
| Push | **未推**（仅本地 feat 分支） |

### 计划结构（与 pr3 同构，按 kickoff §3 强制章节）

1. Context / Approach（PR-4 = 两阶段：Phase 0 FTS5 + Phase 1 Obsidian 页）
2. Schema v4：FTS5 虚表 + triggers + 3 张 publish 表（`rendered_page` / `publish_record` / `publish_run`）
3. Migrations / Paths（`_apply_v4()` + `publish_root()` + env 隔离）
4. 模块拆分 + 4 个新模块的 >8 文件理由
5. Publisher 适配（PUT → GET → SHA，独立 `houchen_publisher`）
6. 6 类页面模板清单（video / concept / claim / forecast / review_queue / coverage）
7. Runner + CLI（`search` / `render` / `publish` + `--apply --operator-authorized` 双门）
8. Fixtures + 测试矩阵（≥ 100 新测试）
9. Critical files 表（17 lib + 5 test + 3 fixture + 2 docs）
10. Verification 命令
11. Out of scope（真模型、向量检索、macro bridge、自定义 UI）
12. 风险（中文 FTS、env 泄漏、宏库耦合、v4 兼容性）
13. 复用与隔离
14. Acceptance checklist

### 关键隔离约定（写进计划正文）

- 默认 `HOUCHEN_PUBLISH_DRY_RUN_ONLY=1`；只有 `--apply --operator-authorized` 双标记才允许真实 PUT
- 新模块**禁止** `import lib/insight_publisher.py`；测试用 grep 守护
- 新模块**禁止**读写 `data/store.db` / `data/insights/` / `data/snapshots/` / `data/ledger.sqlite` / `data/macro.db`
- 不改三份 Codex 基线文档正文，不改两份 DOCX
- 不动 `lib/houchen_quote.exact_quote_in_segment`（PR-2 §8.6 hard gate 复用）
- v4 迁移在无 FTS5 的 SQLite 上 fail-closed

### FTS5 债处理

按 kickoff §2.2 选项 A：FTS5 作为 PR-4 Phase 0（先索引后页面），不使用向量检索；tokenizer 默认 `unicode61`，固定查询集（12–20 条 CJK + EN）作为召回门禁；通过才考虑 n-gram 辅助字段。

### 现状

- `feat/houchen-pr4-plan` 含 1 个新文件：`docs/plans/pr4-obsidian-research-map.md`
- `main` 仍为 `47e4de3`（PR-3 合并后 tip；**未污染**）
- 残留未提交 review 文件（同 kickoff §1 列出的 4 个），仍按 standing orders §4 在当前 feat 分支 docs commit；本回合**不处理**（用户未授权）

### 未做（明示）

- 任何 PR-4 实现代码
- 任何 schema v4 迁移、任何 FTS5 创建
- push `feat/houchen-pr4-plan`（仅本地）
- 真实 Obsidian REST、real model、全频道分析
- merge、force push、push main
- 改 review 残留文件 / 三份 Codex 基线 / 两份 DOCX

### 请 Cursor

请审验 `docs/plans/pr4-obsidian-research-map.md` 并出具 `reviews/PR4_PLAN_AUDIT_*.md`。只有在审计通过且用户/工单明确说「启动 PR-4 实现」后，才开始编码。
