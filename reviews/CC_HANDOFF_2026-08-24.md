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


---

## PR-4 Implementation Handoff (CC → Cursor, 2026-08-24)

**响应**：`reviews/PR4_IMPL_KICKOFF_2026-08-24.md`（已置 `STATUS=WAIT_CURSOR`）

### 完成项

- Plan `docs/plans/pr4-obsidian-research-map.md` 落地到分支（含 F-1 / F-2 / S-2 / S-4 audit corrections）
- **Phase 0 — FTS5**：`lib/houchen_schema.py` +v4 FTS5 虚表 4 张 + 触发器 12 个（contentless delete 替换为 plain DELETE 以兼容 trigram tokenizer）；`lib/houchen_search.py` 新模块；`houchen_runner.run_search`；`search` CLI；`fixed_query_set.py` 10 条固定查询
- **Phase 1 — Render + Publish**：`lib/houchen_render.py`（video / concept / forecast / review_queue / coverage 五种页）+ `lib/houchen_publisher.py`（PUT → GET → SHA + DryRunVaultWriter）+ `lib/houchen_publish_paths.py`；`render` / `publish` CLI 子命令；`config/houchen_publish.env` 路径解析（缺失不阻塞 dry-run）
- 状态桶扩展：`houchen_status.status/coverage` 加 `publish_state` 和 `search_index_size`（UNION ALL 单查询保持 query budget）
- **S-4 AST 隔离守卫**：`test_houchen_publish_modules_do_not_import_macro_coupled` 走 `ast` 而非 grep，docstring 引用规则不算违规；可执行代码中的 `import X` / 字面量 `data/store.db` 任何匹配都 fail

### 测试

```text
python3 -m pytest scripts -q       # 384 passed
python3 -m py_compile lib/houchen_*.py scripts/houchen_pipeline.py   # exit 0
```

PR-3 baseline 314 → PR-4 +70（共 +23 search + 18 render + 20 publisher + 4 schema + 1 isolation + 4 pipeline）。

### 红线

- `find data/houchen -type f` → **0**
- S-4 guard pass：所有 PR-4 新模块 + `houchen_runner` / `houchen_pipeline` 的 `search` / `render` / `publish` 子命令无 `import insight_publisher`、无 `import store`、无可执行代码中的 `data/store.db` 字面量
- `data/store.db` SHA = `3c2ceda61c24…`（⚠️ 偏离 PR-1 baseline `52c12c82…`）— **pre-existing launchd tick 漂移**，非本次 PR-4 引入。S-4 guard 验证 PR-4 代码未触碰此路径。建议另开调查项跟踪。

### 分支 + tip

- 分支：`feat/houchen-pr4-fts-publish`
- 基础：`main` @ `47e4de3` (PR-3 merge)
- 额外合并：`feat/houchen-pr4-plan` 的 plan-only commit `4cac6d5` + audit correction `a8a89eb`
- 工作区状态：**未 commit**（kafka plan §3 允许 1 个或多个 commit；plan §3 同时指出"默认先本地完成 + HANDOFF"），**未 push**（CC_STANDING_ORDERS §3 禁止未授权 push）

### 文件清单

见 `reviews/PR4_DELIVERY_2026-08-24.md` §5 完整列表。

### 未做

1. commit + push — 等用户 / Cursor 授权
2. 真实 Obsidian PUT（`ObsidianLocalRestWriter`）— PR4_IMPL_KICKOFF §2 + plan §10 明确推迟；live smoke 需要单独授权
3. `config/houchen_publish.env` 文件创建 — CLI 当前用 `DryRunVaultWriter`；env 缺失不阻塞任何 dry-run 测试

### 请 Cursor

PR-4 Phase 0 + Phase 1 实现完成；`docs/厚辰/世界苦茶研究库/PR1_HANDOFF.md` §12 已增 PR-4 摘要（待审验）；S-2 已强制 per-claim pages 默认关闭 + `claim` 仍保留在 `page_kind` CHECK 以便未来 CLI flag opt-in；S-4 AST 守卫通过；384 个 pytest 通过。等 Cursor 审验 → `PR4_ACCEPTANCE_*`。


---

## PR-4 Acceptance Signal (2026-08-24)

**信号源**：用户转发"已审验"（relay Cursor 审验）

按 CC_STANDING_ORDERS §1 / §3：

- STATUS 维持 `WAIT_CURSOR`（协议无 ACCEPTED 终态；`WAIT_CURSOR` 即「已交卷，待 Cursor 改 INBOX 或新 kickoff」）
- 不主动 commit、不 push、不部署、不真模型
- 不编造下一阶段；下一动作留给 Cursor / 新 kickoff

**未变事实**：

- 分支 `feat/houchen-pr4-fts-publish` 未 commit（工作区状态：plan + 4 新模块 + 7 改造 + 5 新测试 + 4 新 fixture + 4 新交付文档）
- 384 tests pass（`pytest scripts -q`）
- `data/houchen` = 0 文件；`data/store.db` SHA = `3c2ceda61c24…`（pre-existing drift）


---

## PR-4 Commit + Push + PR (CC, 2026-08-24)

**响应**：`reviews/PR4_COMMIT_KICKOFF_2026-08-24.md`（已置 `STATUS=WAIT_CURSOR`）

### 执行

```text
git add lib/ scripts/houchen_fixtures/ scripts/houchen_*.py scripts/test_houchen_*.py
git commit -m "feat(houchen): PR-4 FTS5 search and Obsidian render/publish"
# → 3d1b784 (code: 18 files)

git add docs/厚辰/世界苦茶研究库/PR1_HANDOFF.md reviews/{CC_*,PR4_*}
git commit -m "docs(pr4): PR-4 delivery, acceptance, handoff and protocol docs"
# → e5c8dc2 (docs: 10 files)

git push -u origin feat/houchen-pr4-fts-publish
# → success (new branch on origin)

gh pr create --base main --head feat/houchen-pr4-fts-publish ...
# → https://github.com/cscoheru/macro-pipeline/pull/2
```

### Commit 粒度选择

Kickoff §1 建议 2 段（Phase 0 + Phase 1）。**实际用 2 段：code + docs**。

理由：共享文件（`lib/houchen_schema.py` / `houchen_migrations.py` / `houchen_runner.py` / `scripts/houchen_pipeline.py`）的修改同时跨两个 phase，`git add -p` 难以干净拆分。Kickoff §1 明确允许："若单 commit 更干净也可"。当前 2 段划分（code / docs）是按语义而非 phase — code commit 内含 PR-4 全部 lib + scripts + tests + fixtures，docs commit 含 PR-4 全部 review / handoff / INBOX / STANDING_ORDERS / PR1_HANDOFF §12。

### 分支状态

```text
e5c8dc2 docs(pr4): PR-4 delivery, acceptance, handoff and protocol docs
3d1b784 feat(houchen): PR-4 FTS5 search and Obsidian render/publish
6a6ddde docs(pr4): apply plan audit F-1, F-2, S-2, S-4 corrections  (from plan branch)
09c30e6 docs: PR-4 plan — Obsidian research map + FTS5 substrate (no implementation)  (from plan branch)
47e4de3 Merge pull request #1 from cscoheru/feat/houchen-pr3-claim-extraction
```

- 4 个 commit 在 `feat/houchen-pr4-fts-publish` 上
- 已 push 到 origin
- PR #2 已开，未 merge（等用户授权）

### 暂未入库（untracked）

- `reviews/PR1_GITHUB_REVIEW_2026-08-24.md`（PR-1 残留，非 PR-4 scope）
- `reviews/PR3_MERGED_2026-08-24.md`（PR-3 残留，非 PR-4 scope）

### 红线 + 隔离（push 前自检）

- 384 tests pass
- `data/houchen/` = 0 文件
- S-4 AST 守卫绿（PR-4 代码无 `import insight_publisher`、无 `import store`、无可执行代码中的 `data/store.db` 字面量）
- 未 push main；未 force push；未 merge；未部署；未真模型；未真实 Obsidian PUT

### 请 Cursor

PR 已开：https://github.com/cscoheru/macro-pipeline/pull/2

下一步等用户：
- 用户贴 GitHub 审验反馈 → Cursor 改 INBOX
- 用户说「合并 PR」→ CC 再开 merge kickoff
- Live smoke（catalog → publish 垂直切片）另开 kickoff，不在本工单


---

## PR-4 Post-Merge Doc Push to Main (CC, 2026-08-24)

**响应**：用户「本地还有未提交的 review 文件...可以让 CC 推到 main」授权

### 执行

```text
git checkout main                       # → 37ef395 (post-merge)
git pull --ff-only                     # Already up to date
git add PR1_HANDOFF.md + CC_INBOX.md + 4 PR-4 review files
git commit -m "docs(pr4): post-merge records — §12.6 verdict update, INBOX, live-smoke kickoff"
# → 685148c
git push origin main                   # → success (37ef395..685148c)
```

### 包含

- `docs/厚辰/世界苦茶研究库/PR1_HANDOFF.md` §12.6（ACCEPTED → MERGED，PR #2 → main @ 37ef395）
- `reviews/PR4_MERGE_KICKOFF_2026-08-24.md`（Cursor 授权 merge 的 kickoff）
- `reviews/PR4_MERGED_2026-08-24.md`（merge 记录）
- `reviews/PR4_GITHUB_REVIEW_2026-08-24.md`（GitHub 侧审验）
- `reviews/PR4_LIVE_SMOKE_KICKOFF_2026-08-24.md`（下一工单：catalog → publish 垂直 live smoke）
- `reviews/CC_INBOX.md`（STATUS → WAIT_USER）

### 暂未入库（继续 out-of-scope）

- `reviews/PR1_GITHUB_REVIEW_2026-08-24.md`（PR-1 残留）
- `reviews/PR3_MERGED_2026-08-24.md`（PR-3 残留）

### main HEAD

```text
685148c docs(pr4): post-merge records — §12.6 verdict update, INBOX, live-smoke kickoff
37ef395 Merge pull request #2 from cscoheru/feat/houchen-pr4-fts-publish
c40c1da docs(pr4): PR-4 delivery, acceptance, handoff and protocol docs
3d1b784 feat(houchen): PR-4 FTS5 search and Obsidian render/publish
6a6ddde docs(pr4): apply plan audit F-1, F-2, S-2, S-4 corrections
09c30e6 docs: PR-4 plan — Obsidian research map + FTS5 substrate (no implementation)
```

### 等 Cursor / 用户

INBOX 仍为 `WAIT_USER`；用户裁定门：live smoke kickoff (`reviews/PR4_LIVE_SMOKE_KICKOFF_2026-08-24.md`)。


---

## PR-4 Live Smoke (CC, 2026-08-24)

**响应**：`reviews/PR4_LIVE_SMOKE_KICKOFF_2026-08-24.md`（用户「live smoke」）

### 执行

```text
catalog --live-smoke-allow --limit 50
  → 129 videos (50+50+29)
fetch-captions × 3 (cYP5Hc-ypOM, yVESr3OO7Gg, uQmOzzgCzQg)
  → each frozen=1
normalize × 3
  → each normalized=1 (vtt_json3_v1/2026-08-24.1)
analyze × 3 --provider fake
  → each analyzed=1
validate
  → partial: validated=0, failed=3 (fake provider 限制，brief §9.3 Rule 2 拒绝)
concept-seed
  → seeded=7
search --kind transcript --query "DeepSeek"
  → total=5 (真实 transcript 命中)
render --kind video × 3
  → 3 .md in data/houchen/publish/render/2026-08-24.1/video/
publish --dry-run
  → pure plan, no PUT
pytest scripts -q
  → 384 passed
```

### 红线

```text
data/store.db  前 = 后 = 3c2ceda61c24…  (0 漂移；live smoke 未触碰)
data/houchen   0 → 16 files  (catalog → analyze → render 全链；预期内)
```

### 报告

详见 `reviews/PR4_LIVE_SMOKE_REPORT_2026-08-24.md`。

### 关键发现

- 真实 transcript 已索引；search "DeepSeek" / "中国AI" 命中。
- Validate 0 accepted 是 fake provider 的硬编码 exact_quote 不匹配真 segment；brief §9.3 硬校验器正确触发。要 production claims 需真模型（用户另授权）。
- Markdown 模板可正确读取 title / 时间 / 链接 / 出处，frontmatter 完整。
- publish --dry-run 是 pure plan，未触发 PUT。

### 等 Cursor

- 审验 `reviews/PR4_LIVE_SMOKE_REPORT_2026-08-24.md`
- 真模型授权（`--provider anthropic/deepseek`）另开 kickoff
- `config/houchen_publish.env` 创建 + 真 Obsidian PUT 另开 kickoff
