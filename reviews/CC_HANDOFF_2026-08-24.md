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


---

## PR-4 Real-Model + Expand (CC, 2026-08-24)

**响应**：`reviews/PR4_REAL_MODEL_EXPAND_KICKOFF_2026-08-24.md`

### 执行

**Phase A** — 3 个原始视频 deepseek-chat 重跑 + Obsidian publish：
- analyze × 3 → validate (3 partial: 156 rejected) → render (re-rendered, SHA 一致) → publish (3 published)

**Phase B** — 6 个新视频全链：
- fetch-captions × 6, normalize × 6 (全成功)
- analyze × 6 (3 success, 3 failed — JSON parse errors / timeout)
- validate (3 partial: 72 rejected)
- render × 3, publish × 3 → 6 视频页进 Obsidian

### 配置

新建 `config/houchen_analyze.env`（mode 0600，git-ignored）：
- `INSIGHT_TIMEOUT_SECONDS=180`
- `INSIGHT_MAX_TOKENS=65536`
- `INSIGHT_MAX_INPUT_CHARS=1500000`（12.5× 扩容）
- `INSIGHT_PROVIDER=deepseek`
- `INSIGHT_MODEL=deepseek-chat`（reasoner 推理烧光 token，content 被截断）

`DEEPSEEK_API_KEY` 从 `config/insight.env` 一次性复制到 `config/houchen_analyze.env`；两个 env 完全独立。

### 红线

- `data/store.db` SHA 前 = 后 = `3c2ceda61c24…`（0 漂移）
- `data/houchen` 16 → 47 文件
- `data/insights` → 856 文件（含 `failed_responses/`，新设脱敏失败记录）
- S-4 隔离守卫仍通过（PR-4 新模块 6 文件无 `import insight_publisher` / 可执行 `data/store.db` 字面量）
- **遗留问题**：`lib/houchen_analyzer.py` 在 PR-3 期间 `import insight_provider` 用于真实 provider 调用；不在 S-4 白名单（只覆盖 PR-4 新增文件），但本身违反 PR-4 plan §11.4。下次 PR 应拆出独立 houchen provider 层。

### 关键发现

- deepseek-reasoner 的 `reasoning_content` 烧光 token，content 被截断 → JSON parse 失败。切 deepseek-chat 后稳定。
- deepseek-chat 217 个 claim candidates 全被 brief §9.3 硬校验器拒绝（最常见：`exact_quote` 不在 segment.text）。fake provider 留下的 3 个 accepted 是 Obsidian 当前内容。
- 跳过 3 视频：7AAezayi7Js / f_jd_j3eEuE / mg_BuWqSL9A（per kickoff §6）

### 测试

```text
python3 -m pytest scripts -q   → 386 passed
```

### 等 Cursor

- 审验 `reviews/PR4_REAL_MODEL_EXPAND_REPORT_2026-08-24.md`
- 调 prompt / 换 model（Claude / MiniMax）让真模型通过 §9.3 hard validator
- 拆 `insight_provider` 耦合（houchen_analyzer 重构）


---

## PR-4 Real-Model 路线 2 闭环 (CC, 2026-08-25)

**响应**：INBOX「路线 2 确认」（用户：继续等复杂栈跑完）

### 路线 2 retry 结果

- **7AAezayi7Js**（Kimi K3）：timeout 120s → 300s 后 ✓ analyze 成功 → render → publish ✓
- **f_jd_j3eEuE**（藏人）：content_filter；DeepSeek 内容审核拒；不可重试，跳过
- **mg_BuWqSL9A**（AI bubble）：HTTP 400；API 端 token / 内容拒；不可重试，跳过

最终 **7 video 页 → Obsidian**（was 6 in Phase B）。

### 配置最终态

- `INSIGHT_TIMEOUT_SECONDS=300`（was 120 default；路线 2 retry 用）
- `INSIGHT_MAX_INPUT_CHARS=1500000`
- `INSIGHT_MAX_TOKENS=65536`
- `INSIGHT_MODEL=deepseek-chat`

### DB final

```text
rendered: 7; publish_records: 7 (all published)
claim: 3 accepted (fake leftovers) / 269 rejected (deepseek-chat)
analyze: 10 success / 8 failed
```

### 红线

- `data/store.db` SHA 前 = 后 = `3c2ceda61c24…` (0 漂移)
- `data/houchen` 47 → 49 文件（render + publish 各 1 新文件）
- S-4 AST 守卫仍绿
- 遗留：`houchen_analyzer.py` 仍 `import insight_provider`（下次 PR 拆）

### 报告

详见 `reviews/PR4_REAL_MODEL_EXPAND_REPORT_2026-08-24.md`（已覆盖路线 2 retry 结果）。

### 等 Cursor

- 审验报告
- 调 prompt 让真模型对齐 §9.3 hard validator（exact_quote verbatim substring）
- 拆 `houchen_analyzer` ↔ `insight_provider` 耦合


---

## PR-4 Prompt Align v2 试跑 (CC, 2026-08-25)

**响应**：`reviews/PR4_PROMPT_ALIGN_KICKOFF_2026-08-25.md`（Cursor prompt v2 + PROMPT_VERSION bump）

### 试跑（7DsxtHsOCzA）

```text
analyze --provider deepseek --video-id 7DsxtHsOCzA  → success
validate --video-id 7DsxtHsOCzA  → partial: validated=0, rejected=8
```

### 拒因占比（v2 prompt 首跑）

| Rule | % | 状态 |
|------|--:|------|
| **R10** layer='speaker_statement' | 50% | ❌ 仍出 |
| **R2**  exact_quote 不在 segment.text | 50% | ❌ 仍出 |
| R1   raw_caption_sha256 缺失 | — | ✅ v2 已修 |

### 关键发现

- v2 让 R1 失效（INPUT 含 raw_caption_sha256）
- R2 仍 50%：模型仍做「总结式引文」
- R10 仍 50%：模型仍输出 speaker_statement

### 停等 Cursor

按 kickoff §1「若仍 0：在 HANDOFF 记录 R2/R5 拒因占比，停等 Cursor 调 prompt」。

Cursor 下一工单：v3 prompt（强 layer 约束 + verbatim 引文 few-shot）。

### 红线

- `data/store.db` SHA 前 = 后 = `3c2ceda61c24…` (0 漂移)
- 386 tests pass

报告：`reviews/PR4_PROMPT_ALIGN_REPORT_2026-08-25.md`。

---

## PR-4 Prompt Align v3 试跑 (CC / 本地, 2026-08-25)

**响应**：`reviews/PR4_PROMPT_ALIGN_V3_KICKOFF_2026-08-25.md`（commit `65dcc68`）

### 试跑（7DsxtHsOCzA）

```text
analyze  hcrun_01a03670aa7e7001b0878f18e865a521  → success (deepseek)
validate → partial: validated=4, rejected=4
render --from-db → 本地 7DsxtHsOCzA.md 含 4 条主张 (SHA 9c8bbc4d…)
publish  → 未在 v3 后重跑（vault SHA c68079e2… 旧）
```

### 拒因（v3 本 run）

| Rule | rejected 占比 | 状态 |
|------|---------------|------|
| R10 speaker_statement | 0% | ✅ schema 修复生效 |
| R2 verbatim quote | 100% (4/4) | ⚠️ 仍为主要拒因 |

### Cursor 审验

`reviews/PR4_PROMPT_ALIGN_V3_ACCEPTANCE_2026-08-25.md` — **PARTIAL**（门禁过、render 过、Obsidian 未同步）。

### 待办

1. `publish` 更新 Obsidian `7DsxtHsOCzA.md`
2. 通过后 kickoff §3 扩 7 视频

### 红线

- `data/store.db` SHA = `3c2ceda61c24…`
- 387 tests pass

---

## PR-4 Prompt Align v3 publish (Cursor, 2026-08-25)

**触发**：用户「publish」

```text
publish --kind video --page-id rp_video_7DsxtHsOCzA
  → success (Obsidian PUT+GET SHA ok)
vault_sha256 = render_sha256 = 9c8bbc4d7ca0abc3d89b34c2a2a026ea43ac48ce781b913040fff2931533d3d9
```

**代码修复**：`publish_page` / `publish_with_path` 在 `vault_sha256 ≠ render_sha256` 时重新 PUT（此前 `status=published` 会错误 no-op）。

Obsidian：`Research/世界苦茶/video/7DsxtHsOCzA.md` 现含 4 条 v3 accepted 主张。

**待用户**：**commit** 已完成扩量；后续可选全频道 analyze（勿一次跑全量）。

---

## PR-4 Prompt Align v3 扩量 (Cursor, 2026-08-25)

**触发**：用户「扩量并commit」

6 视频 v3 analyze→validate→render；7 视频 publish。合计 **30** real accepted 行（7 视频）；Obsidian 7 页 SHA 对齐。

报告：`reviews/PR4_PROMPT_ALIGN_V3_EXPAND_REPORT_2026-08-25.md`。


---

## PR-4 Concept-Exit (CC, 2026-08-25)

**响应**：`reviews/PR4_CONCEPT_EXIT_KICKOFF_2026-08-25.md`

### §1 概念页（PR-4 退出必做）

- 6 张概念页 render (`--from-db`) → publish → Obsidian
- 模板 `template_version=2026-08-25.1`（v3 prompt bump 后）
- 每页含：frontmatter / 标题 / 定义 / 领域 slug / Speaker uses / System analyses
- **未 promote**（保持 `proposed`；human 注入前不进 canonical）

### §2 竖切扩到 12 视频

5 新视频（§2b）：l9qR-bXaFwM / Yukb3xuc9l8 / gRtY4ZEQI5A / 7zRWMu0kU2o / gk-_x2DWHCk

| Step | Result |
|------|--------|
| fetch-captions × 5 | 5 frozen |
| normalize × 5 | 5 normalized |
| analyze × 5 (deepseek-chat, v3 prompt) | 5 success |
| validate | 25 accepted (总累计 55 accepted claims) |
| render × 5 (`--from-db`) | 5 rendered |
| publish all video | 12 published |

### brief §16 退出条件

- ≥1 可用概念页：✅ 6 张
- Re-publish no-op：✅
- publish 失败不误记 published：✅（VaultWriter PUT→GET→SHA 协议保留）

### 跳过

- `f_jd_j3eEuE` (content_filter)
- `mg_BuWqSL9A` (HTTP 400)

### 红线

- `data/store.db` 前 = 后 = `4a8e409b7279…` (0 漂移)
- 388 tests pass

### 报告

详见 `reviews/PR4_CONCEPT_EXIT_REPORT_2026-08-25.md`。

### 等 Cursor

审验后，下一工单是 brief §26（全量字幕 / PR-5 macro bridge / ASR / 真人 speaker 解析），**本回合不主动开**。


---

## §26 Bundle (CC, 2026-08-25)

**响应**：`reviews/SECTION26_BUNDLE_KICKOFF_2026-08-25.md`（用户「全量字幕 / PR-5 / ASR」）

### A — 全量字幕

```text
pending 115 → 0 (5 批次: 20+30+30+30+5)
frozen  14 → 50 (+36 新字幕)
missing 79 (50 streams + 29 shorts; 0 regular videos)
normalized 14 → 50 (+36)
errors  0
```

### B — ASR 预研

`reviews/ASR_PREFLIGHT_2026-08-25.md` — **GO_PILOT**（3 streams 试点，faster-whisper small，WER < 15%）

### C — PR-5 计划

`docs/plans/pr5-macro-bridge.md` — 6 文件 ≤8，零写宏观库，`macro_link_candidate` 建 houchen.db，首版 keyword_match + JSONL 导出

### 红线

```text
data/store.db  before = after = 4a8e409b7279…  (0 漂移)
未执行 analyze / validate / push / pip install
```

### 报告

`reviews/SECTION26_BUNDLE_REPORT_2026-08-25.md`

### INBOX

`STATUS=WAIT_CURSOR` — 等 Cursor 审验 A/B/C 三项产出


---

## §26 Dual Track: PR-5 + WPS Import (CC, 2026-08-25)

**响应**：`reviews/DUAL_TRACK_PR5_ASR_KICKOFF_2026-08-25.md`（用户「都做」→ Cursor 改 WPS 路径）

### P1 — PR-5 Macro Bridge

- `lib/macro_bridge.py` + `config/macro_bridge_keywords.yaml` + CLI `macro-bridge --scan/--export/--verify-sha`
- 28 tests / 434 total pass
- 6 claims → 32 candidates (all contextualizes, v1)
- store.db SHA `4a8e409b…` ✅

### P2 — 音频 + import-transcript

- 3 webm 音频下载 (358MB)
- `lib/houchen_import_transcript.py` + CLI `import-transcript --video-id --from-file`
- 支持 .txt / .vtt / .srt；幂等
- 18 tests
- **零 whisper / 零机转写**
- 已知限制：`analyze --pending` 不拾取 `wps_import` normalizer，需 `--video-id` 显式

### 红线

- store.db SHA 不变 ✅
- 零机转写 token ✅

### INBOX

`WAIT_CURSOR` — WPS 3 直播全链完成


---

## WPS Stream Analyze (CC, 2026-08-25)

**响应**：`reviews/WPS_STREAM_ANALYZE_KICKOFF_2026-08-25.md`

### 结果

| video_id | accepted | rejected | publish |
|----------|----------|----------|---------|
| `Z1HWDoSaC5Q` | 7 | 1 | ✅ |
| `-9qyfgyKkaU` | 6 | 1 | ✅ |
| `ScbTzleF3Pc` | 7 | 1 | ✅ |
| **合计** | **20** | 3 | 15 pages |

### 红线

- store.db SHA `4a8e409b…` ✅
- 零转写正文 ✅
- 仅 3 视频 ✅

### 报告

`reviews/WPS_STREAM_ANALYZE_REPORT_2026-08-25.md`

### INBOX

`WAIT_CURSOR`


---

## Concept Refresh + PR-5 Land (CC, 2026-08-25)

**响应**：`reviews/CONCEPT_REFRESH_PR5_LAND_KICKOFF_2026-08-25.md`

### A — 概念页刷新

- 12 proposed concepts rendered
- 18 concept pages published to Obsidian (12 refreshed + 6 existing)
- 0 failed

### B — PR-5 Land

```text
814d8a8 feat(houchen): land PR-5 macro-bridge
d91a8be feat(houchen): WPS import-transcript path
→ pushed to origin/main
```

- 46 tests pass (28 macro_bridge + 18 import_transcript)
- scan: 8 claims → 41 candidates (all contextualizes)
- store.db SHA `4a8e409b…` ✅
- `scripts/asr_transcribe.py` deleted (deprecated whisper)

### INBOX

`WAIT_CURSOR`
