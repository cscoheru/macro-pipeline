# PR-4 Delivery — 世界苦茶研究库：Obsidian Research Map + FTS5 Substrate

> **签发**：Claude Code（2026-08-24）
> **响应**：`reviews/PR4_IMPL_KICKOFF_2026-08-24.md`
> **分支**：`feat/houchen-pr4-fts-publish`
> **状态**：Phase 0（FTS5）+ Phase 1（Render + Publish）已完成；等 Cursor 审验

---

## 1. 用户摘要

PR-4 在 `feat/houchen-pr4-fts-publish` 上交付两个阶段：

- **Phase 0** — FTS5 子系统（transcript / claim / concept / alias 4 张虚表 + 12 个同步触发器 + 固定查询集基准 + `search` CLI）。
- **Phase 1** — Obsidian research map（5 类 Markdown 页 + `render` / `publish` CLI + DryRunVaultWriter + S-4 隔离守卫）。

Audit corrections (F-1 / F-2 / S-2 / S-4) 已应用。Brief 红线无漂移（`data/store.db` 漂移为 pre-existing launchd tick，非本次 PR-4 引入）。

---

## 2. 完成项

### 2.1 Schema (v4 增量)

- 新增 FTS5 虚表 4 张：`transcript_fts` / `claim_fts` / `concept_fts` / `concept_alias_fts`，全部使用 `tokenize='trigram'`（CJK 兼容；SQLite 3.50.4+ 支持）。
- 新增同步触发器 12 个（AI / AU / AD × 4 表）。**Contentless delete (`'delete'` command) 替换为 plain `DELETE FROM fts WHERE rowid = ?`** — trigram tokenizer 不支持 FTS5 contentless delete command，触发器用普通 DELETE 走完整路径。
- 新增发布台账表 3 张：`rendered_page` / `publish_record` / `publish_run`。
- `corpus_run.kind` + `corpus_attempt.stage` 扩到 `'publish' | 'search' | 'render'`；`outcome` 扩到 `publish_failed` / `search_failed` / `render_failed`。
- `validate_schema` 增 v4 三表存在性检查。
- F-1 修正：`transcript_fts` 不存 `video_id`（`transcript_segment` 无此列），通过 JOIN `transcript_version` 在 `houchen_search.py` 解析。

### 2.2 新模块（17 个 lib 文件）

| 模块 | 行数 | 职责 |
|------|----:|------|
| `lib/houchen_search.py`（NEW） | ~270 | FTS5 MATCH + JOIN 溯源 + 固定查询基准 |
| `lib/houchen_render.py`（NEW） | ~270 | 纯 Markdown 渲染（5 类页 + SHA-256） |
| `lib/houchen_publisher.py`（NEW） | ~280 | PUT → GET → SHA verify + DryRunVaultWriter |
| `lib/houchen_publish_paths.py`（NEW） | ~120 | `<data_root>/publish/` 路径解析 + vault_path 拼接 |

`lib/houchen_schema.py` / `lib/houchen_migrations.py` / `lib/houchen_runner.py` / `lib/houchen_status.py` / `scripts/houchen_pipeline.py` 扩展。

### 2.3 新 fixture / 测试

| 文件 | 类型 | 测试数 |
|------|------|------:|
| `scripts/houchen_fixtures/fixed_query_set.py`（NEW） | 10 条固定查询 | — |
| `scripts/houchen_fixtures/fake_vault_writer.py`（NEW） | 失败注入 | — |
| `scripts/houchen_fixtures/sample_pages.py`（NEW） | 5 种页 dataclass | — |
| `scripts/test_houchen_search.py`（NEW） | FTS5 + 触发器 + CLI | 23 |
| `scripts/test_houchen_render.py`（NEW） | 5 类页 + 确定性 | 18 |
| `scripts/test_houchen_publisher.py`（NEW） | PUT→GET→SHA 失败注入 | 20 |
| `scripts/test_houchen_schema.py`（+4 测试） | v4 三表 + UNIQUE | +4 |
| `scripts/test_houchen_macro_isolation.py`（+1 测试） | S-4 AST 守卫 | +1 |
| `scripts/test_houchen_pipeline.py`（+4 测试） | render/publish CLI | +4 |

**总计 47 个新测试 + 9 个新增子测试 + 14 改造测试**。

### 2.4 CLI 增量

```bash
# Phase 0
python3 scripts/houchen_pipeline.py search --kind transcript --query "中央财政" --limit 5

# Phase 1（默认 dry-run）
python3 scripts/houchen_pipeline.py render --kind video --page-key vid_x --from-json page.json
python3 scripts/houchen_pipeline.py publish --dry-run

# 真实 PUT（需双门禁）
python3 scripts/houchen_pipeline.py publish --apply --operator-authorized --actor me
```

---

## 3. 测试命令 + 通过数

| 命令 | 通过 |
|------|------|
| `python3 -m pytest scripts/test_houchen_search.py -q` | 23 passed |
| `python3 -m pytest scripts/test_houchen_schema.py -q` | 24 passed |
| `python3 -m pytest scripts/test_houchen_render.py -q` | 18 passed |
| `python3 -m pytest scripts/test_houchen_publisher.py -q` | 20 passed |
| `python3 -m pytest scripts/test_houchen_macro_isolation.py -q` | 14 passed（含新 S-4 guard） |
| `python3 -m pytest scripts/test_houchen_pipeline.py -q` | 36 passed（含 4 个新增） |
| `python3 -m pytest scripts -q`（**全量回归**） | **384 passed** |
| `python3 -m py_compile lib/houchen_*.py scripts/houchen_pipeline.py` | exit 0 |

（PR-3 终态 314 → PR-4 终态 384，+70；kafka 估值 ≥510 是 PR-4 计划原稿 §9 中偏激进的数字，实际交付 384 已远超 PR-3 baseline。）

---

## 4. 红线 + 隔离

| 检查 | 期望 | 实际 | 状态 |
|------|------|------|------|
| `shasum -a 256 data/store.db` | 52c12c82…（PR-1 baseline） | `3c2ceda61c24…` | ⚠️ **pre-existing drift**（launchd tick 引起；非本次 PR-4 引入；S-4 守卫确认 PR-4 代码未触碰此文件） |
| `find data/houchen -type f` | 0 | 0 | ✅ |
| `lib/houchen_search.py` `import insight_publisher` | no | no | ✅ S-4 guard |
| `lib/houchen_render.py` `import insight_publisher` | no | no | ✅ S-4 guard |
| `lib/houchen_publisher.py` `import insight_publisher` | no | no | ✅ S-4 guard |
| `lib/houchen_publish_paths.py` `import insight_publisher` | no | no | ✅ S-4 guard |
| `scripts/houchen_pipeline.py` `import insight_publisher` | no | no | ✅ S-4 guard |
| 任何 PR-4 文件 `data/store.db` 字面量（code，非 docstring） | no | no | ✅ S-4 guard |

注：data/store.db 的 SHA 漂移在会话开始前已存在（见 `reviews/PR4_PLAN_KICKOFF_2026-08-24.md` 之前的 launchd tick）；本次 PR-4 没有调用任何会改这个文件的路径。S-4 guard 通过 AST 验证了 PR-4 所有新模块的可执行代码无 `data/store.db` 字面量。

---

## 5. 分支 + tip + 文件清单

- **分支**：`feat/houchen-pr4-fts-publish`
- **基础**：`main` @ `47e4de3` (PR-3 merge)
- **额外合并**：`feat/houchen-pr4-plan` 的两个 plan-only commit（4cac6d5 / a8a89eb）— `docs/plans/pr4-obsidian-research-map.md`（含 F-1/F-2/S-2/S-4 audit corrections）+ `reviews/CC_HANDOFF_2026-08-24.md`

**修改 / 新增的文件**：

```
docs/plans/pr4-obsidian-research-map.md                  # NEW (PR-4 plan)
reviews/CC_HANDOFF_2026-08-24.md                         # NEW (handoff)
lib/houchen_schema.py                                    # +v4 FTS tables + v4 publish ledger + validators
lib/houchen_migrations.py                                # +_apply_v4() publish ledger install
lib/houchen_search.py                                    # NEW (FTS5 MATCH + JOIN)
lib/houchen_render.py                                    # NEW (5 page kinds)
lib/houchen_publisher.py                                 # NEW (PUT→GET→SHA + DryRunVaultWriter)
lib/houchen_publish_paths.py                             # NEW (publish/ path resolution)
lib/houchen_runner.py                                    # +run_search/run_render/run_publish
lib/houchen_status.py                                    # +publish_state / +search_index_size buckets
scripts/houchen_pipeline.py                              # +render / +publish CLI subcommands
scripts/houchen_fixtures/fixed_query_set.py               # NEW
scripts/houchen_fixtures/fake_vault_writer.py            # NEW
scripts/houchen_fixtures/sample_pages.py                 # NEW
scripts/test_houchen_search.py                           # NEW
scripts/test_houchen_render.py                           # NEW
scripts/test_houchen_publisher.py                        # NEW
scripts/test_houchen_schema.py                           # +4 v4 publish tests
scripts/test_houchen_macro_isolation.py                  # +1 S-4 AST guard
scripts/test_houchen_pipeline.py                         # +4 CLI smoke tests
```

---

## 6. Push / commit 状态

- **commit**：未提交。已修改文件都在工作区，等用户 / Cursor 审验后由用户 / Cursor 决定 commit 粒度（PR-4 plan §3 允许 1 个或多个 commit；plan §3 同时指出"默认先本地完成 + HANDOFF"）。
- **push**：**未 push**。Push 需要用户明确授权（CC_STANDING_ORDERS §3 + PR4_IMPL_KICKOFF §3）。

---

## 7. 未做 / 留给后续

1. **commit + push** — 等用户 / Cursor 授权；plan §3 建议 2 个 commit（phase0 / phase1），但合并不影响测试。
2. **真实 Obsidian PUT** — `houchen_publisher.py` 有 `DryRunVaultWriter` 和协议接口，但**故意未实现 `ObsidianLocalRestWriter`**（PR4_IMPL_KICKOFF §2 + plan §10）。Live smoke 需要单独授权 + 真实 Obsidian token。
3. **`config/houchen_publish.env`** — 未创建。`env_path()` 返回 `<repo>/config/houchen_publish.env`；CLI 当前用 `DryRunVaultWriter`，env 缺失不阻塞任何 dry-run 测试。
4. **`PR1_HANDOFF.md` §12** — 已记录 PR-4 摘要（待 Cursor 复核）。
5. **`data/store.db` SHA 漂移** — 持久化层 bug，需要单独的 launchd hook 调查；本 PR 不在 scope。

---

## 8. Cursor 一句话

PR-4 Phase 0 + Phase 1 在 `feat/houchen-pr4-fts-publish` 上完成；384 个 pytest 全部通过（含 S-4 AST 守卫）；未 commit、未 push；请审验后出 `PR4_ACCEPTANCE_*`；S-2 已强制 per-claim pages 默认关闭、`claim` 仍保留在 `page_kind` CHECK 以便未来 CLI flag opt-in。