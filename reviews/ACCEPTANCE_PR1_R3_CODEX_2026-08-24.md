# PR-1 第三轮独立验收报告（Codex / Cursor）

日期：2026-08-24  
轮次：R3（针对 `PR1_HANDOFF.md` R3 Resubmission）  
结论：**PASS**（功能 + 新红线基线）  
下一阶段：**可进入 PR-2 规划/实施**（live smoke 仍待用户联网授权）  
验收方式：只读代码审查、离线 pytest、`py_compile`、SHA/mtime 红线核验、launchd/log 溯源；未修改实现代码

---

## 0. 结论摘要

R3 实现与测试在 R2 §5/§6 所列 **P0/P1/P2 全部有 fix + 测试证据**；4 个测试套件 **83/83**、扩展 **100/100**、全 `scripts` **192/192** 通过；负向用例抽查为真分支。

首轮复验因 `data/store.db` SHA 偏离 R2 基线判定 FAIL。用户于 **2026-08-24 授权接受新红线基线**；handoff §9 已记录溯源与隔离证据。本轮独立复验：

- 新基线 SHA `52c12c82…` + mtime `2026-08-24 09:07:28`：**匹配**
- launchd `09:07` + `pipeline.log` `09:07:29` 完成：**匹配**（宏观 fetch，非 houchen）
- houchen 对 `store.db` 仅 protected-path 声明，无读写路径：**匹配**
- 5 份基线文件 SHA：**全部匹配** handoff §8
- `data/houchen/` 0 文件：**匹配**

**最终裁定：PR-1 PASS（functional）+ ACCEPTED NEW RED-LINE BASELINE。**

---

## 1. R2 §5 / §6 / §8 问题标号清单

### §5 仍未关闭的阻断问题（P0 / P1）

| 标号 | 标题 |
|------|------|
| **P0-1** | 生产默认 DB leaf 未拒绝 symlink，可修改 data-root 外的 SQLite |
| **P0-2** | 派生目录 symlink 未校验，`ensure_dirs()` 可写到研究根之外 |
| **P0-3** | no-replace 降级路径仍可覆盖竞态目标，并接受 symlink target |
| **P0-4** | 目录 fsync 错误被吞掉，durability 保证不成立 |
| **P1-1** | schema validation 并不「精确」，同名空 trigger 可冒充 frozen guard |
| **P1-2** | dry-run 只修了 fetch；catalog 和 preflight 仍写磁盘 |
| **P1-3** | 状态与 pending 查询违反 SQL aggregate / no-N+1 基线 |
| **P1-4** | 高优先字幕候选下载失败不会回退到有效候选 |
| **P1-5** | catalog partial 的失败 tab/reason 在 coverage 中不可见 |
| **P1-6** | 所谓 full macro isolation test 不是完整 CLI/磁盘链路 |

### §6 P2 重要问题

| 标号 | 标题 |
|------|------|
| **P2-1** | 显式未编目 ID 返回进程成功且缺乏可审计 ID |
| **P2-2** | `tool_error` 在 status 中消失，status/coverage 分类不一致 |
| **P2-3** | stdout/stderr/字幕 byte limits 不是主动资源边界 |
| **P2-4** | 负数 `--limit` 被解释为 Python 负切片 |
| **P2-5** | handoff 中若干测试声明与实际测试不符 |

### §8 Claude Code 修订顺序（8 步）

1. 先修 4 个 P0：默认 DB leaf no-follow、派生目录逐组件 no-follow、真正 no-replace 安装、目录 fsync 失败向上传播  
2. 补全 schema exact validation 与伪 trigger/FK/index/constraint 测试  
3. 统一所有 dry-run 入口，完整目录树 snapshot 验证零副作用  
4. 状态推导改为公共 SQL aggregate/CTE，修 status/coverage/pending/limit  
5. 修候选级 fallback、partial gap 可见性、未编目 ID 非成功与 tool_error 分类  
6. 修主动资源上限和负数 limit  
7. 用真实 CLI + 磁盘研究 DB 重做 macro isolation E2E  
8. 更新 handoff，只声明真正由测试触发的证据；交回 Codex，不得进入 PR-2  

---

## 2. Fix → Test 映射核验（对照 PR1_HANDOFF §2 / §3 / §4）

Handoff 为每个 R2 项声明了 fix 与测试；本轮对照结论：**映射完整且测试名在仓库中存在**。

| R2 项 | Handoff 测试（§2–§4 / §6 checklist） | 映射状态 |
|-------|--------------------------------------|----------|
| P0-1 | `test_default_connect_rejects_db_symlink`, `test_db_symlink_rejected` | ✅ |
| P0-2 | `test_data_root_rejects_symlink_component`, `test_data_root_rejects_symlink_middle_component`, `test_ensure_dirs_rejects_symlink_raw`, `test_ensure_dirs_rejects_symlink_captions` | ✅ |
| P0-3 | `test_install_content_addressed_rejects_symlink_target`, `_directory_target`, `_fifo_target`, `test_install_content_addressed_hardlink_failure_fails_closed`, `test_install_content_addressed_hardlink_fail_racing_target_untouched` | ✅ |
| P0-4 | `test_install_content_addressed_dir_fsync_failure`, `test_freeze_dir_fsync_failure_no_raw_row`, `test_install_content_addressed_fsync_failure_no_install` | ✅ |
| P1-1 | `test_validate_schema_rejects_empty_trigger`, `_wrong_index_column`, `_missing_fk`, `_wrong_check`, `test_failed_ddl_rolls_back_fully` | ✅ |
| P1-2 | `test_dry_run_zero_filesystem_change`, `test_dry_run_zero_change_on_existing_root` | ✅ |
| P1-3 | `test_status_query_count_fixed`, `test_video_states_query_uses_indexes` | ✅ |
| P1-4 | `test_freeze_manual_download_fails_falls_back_to_auto` | ✅ |
| P1-5 | `test_coverage_shows_partial_gap` | ✅ |
| P1-6 | `test_full_pr1_cli_run_leaves_macro_unchanged` | ✅ |
| P2-1 | `test_fetch_uncataloged_id_returns_failed`, `test_cli_fetch_uncataloged_id_nonzero` | ✅ |
| P2-2 | `test_tool_error_consistent_in_status_and_coverage` | ✅ |
| P2-3 | `test_run_bounded_timeout_kills_group`, `test_run_bounded_kills_on_stderr_overflow`, `test_run_bounded_kills_on_stdout_overflow`, `test_run_bounded_watch_path_byte_limit` | ✅ |
| P2-4 | `test_limit_negative_rejected_runner`, `test_cli_limit_negative_rejected`, `test_limit_values_cli` | ✅ |
| P2-5 | 上述测试更名/增强（见 handoff §4） | ✅ |

---

## 3. 8 个实现文件 fix 落点（handoff 行号对照）

| 文件 | Fix 落点 | 核验 |
|------|----------|------|
| `lib/houchen_store.py` | `ensure_dirs()` L30–47：`assert_no_symlink_components` 先于 `makedirs`；`connect()` L50–77：默认路径 L67 调用 `assert_no_symlink_components`，在 `sqlite3.connect` 之前 | ✅ P0-1/P0-2 |
| `lib/houchen_paths.py` | `_reject_symlink_ancestors` L85–105；`assert_no_symlink_components` L227–250；`resolve_data_root` L107–126 | ✅ P0-2 |
| `lib/houchen_acquisition.py` | `_fsync_dir` L534–552 仅吞 `ENOTSUP`/`EINVAL`；`_target_lstat` L555–567；`install_content_addressed` L570–623 无 rename fallback；`_GLOBAL_ERROR_CLASSES` + freeze loop L910–912 候选级继续；`_run_bounded` L169+ 溢出杀进程组 | ✅ P0-3/P0-4/P1-4/P2-3 |
| `lib/houchen_schema.py` | `validate_schema` L478+ 完整 xinfo/FK/index/CHECK/trigger body；`video_states` / `pending_video_ids` L620+ 单 SQL CTE | ✅ P1-1/P1-3 |
| `lib/houchen_migrations.py` | 原子 v1 + exact-schema gate（handoff；与 schema 测试联动） | ✅ |
| `lib/houchen_runner.py` | `run_fetch_captions` L300–317 未编目 ID 前置拒绝；`_validate_limit`；`_select_scope` 复用 pending SQL | ✅ P2-1/P2-4/P1-3 |
| `lib/houchen_status.py` | `_state_counts` L35–47 单次 `video_states`；`captions.tool_error` L62–71；`coverage` L88 `_catalog_partial` | ✅ P1-3/P1-5/P2-2 |
| `scripts/houchen_pipeline.py` | `cmd_preflight` L132–144 dry-run 零写；`cmd_catalog` L163–175 内存 DB；`_nonneg_int` limit；exit code 语义 | ✅ P1-2/P2-4 |

`python3 -m py_compile` 上述 8 文件：**exit 0**。

---

## 4. 测试执行与负向用例抽查

### 4.1 命令与结果

```text
$ python3 -m pytest scripts/test_houchen_schema.py \
    scripts/test_houchen_acquisition.py \
    scripts/test_houchen_pipeline.py \
    scripts/test_houchen_macro_isolation.py -q
83 passed in 5.52s

$ python3 -m pytest scripts/test_houchen_*.py \
    scripts/test_ledger.py scripts/test_migrations.py -q
100 passed in 5.53s
```

分项：schema 16，acquisition 35，pipeline 19，macro-isolation 13。

### 4.2 负向用例抽查（2–3 项真伪）

| 测试 | 声称覆盖 | 真伪判定 | 依据 |
|------|----------|----------|------|
| `test_default_connect_rejects_db_symlink` | P0-1 默认 `connect()` 拒绝 DB symlink，外部 0 字节不变 | **真** | 调用无参 `houchen_store.connect()`；`external.read_bytes() == b""` |
| `test_install_content_addressed_hardlink_fail_racing_target_untouched` | P0-3 竞态目标不被 rename 覆盖 | **真** | `monkeypatch` 在 `link` 内先写入 `competitor bytes` 再抛 EXDEV；断言目标仍为 competitor 内容 |
| `test_validate_schema_rejects_empty_trigger` | P1-1 R2 探针：同名 `SELECT 1` trigger | **真** | 显式 DROP 真 trigger 并 CREATE 空 trigger；`validate_schema` 返回 False |

---

## 5. 不可变项核验

| 项目 | R2 基线 | 本轮实测 | 结果 |
|------|---------|----------|------|
| `data/store.db` SHA-256 | R2: `38328cd0…` | `52c12c82…`（**新接受基线**，§9.5 用户授权） | **PASS**（re-baselined） |
| `data/store.db` mtime | R2 时未变 | `2026-08-24 09:07:28` | **与 launchd 09:07 macro run 一致** |
| `data/houchen/` 业务文件数 | 0 | `find … -type f` → **0** | **PASS** |
| `docs/厚辰/不明白访谈厚辰.docx` | SHA 前缀 `5b1ec484…` | `5b1ec4840c08…` mtime `2026-08-22 09:50:32` | **PASS** |
| `docs/厚辰/重庆上街-厚辰.docx` | SHA 前缀 `c5840da9…` | `c5840da93b30…` mtime `2026-08-23 12:13:31` | **PASS** |
| `CLAUDE_CODE_IMPLEMENTATION_BRIEF.md` | R2：与 R1 基线一致 | SHA `0146a312…` mtime `2026-08-23 16:36:50` | **PASS**（未见 R1 全文 SHA 存档，mtime 与 R2 日一致） |
| `CODEX_ACCEPTANCE_PROTOCOL.md` | 同上 | SHA `8c5b1ac4…` mtime `2026-08-23 16:36:50` | **PASS** |
| `ENGINEERING_TEST_PLAN.md` | 同上 | SHA `ef337675…` mtime `2026-08-23 16:36:04` | **PASS** |

说明：`PR1_HANDOFF.md` 为每轮提交文档，R3 增补 §9 属预期，**不纳入**「不可修改 Codex 基线文档」红线。

### 5.1 溯源独立核验（§9.2）

| 证据 | 结果 |
|------|------|
| `com.kjonekong.macro-pipeline.plist` Hour=9 Minute=7 | ✅ |
| `logs/pipeline.log` 2026-08-24 09:07:01–09:07:29（jp_gdp/de_* + `run done`） | ✅ |
| `grep store.db` 于 `houchen_*` 仅 `houchen_paths.py` protected 列表 | ✅ |
| `HOUCHEN_DATA_ROOT` 于 test/CLI 共 43 处 | ✅ |
| `.gitignore` 含 `data/` → store.db 不可 git 恢复 | ✅ |

**红线结论：接受 `52c12c82…` 为新基线；PR-1 代码不可能造成该变更。**

---

## 6. 功能验收矩阵（R3 代码层，不含红线）

| 能力 | R2 | R3（本轮） | 说明 |
|------|----|------------|------|
| 红线 / 范围控制 | PASS | **PASS**（re-baselined §9） | 新 SHA 已接受 |
| P0 symlink / no-replace / fsync | FAIL | **代码+测试 PASS** | 落点与负向测试成立 |
| P1 schema / dry-run / SQL / fallback / coverage / E2E | FAIL | **代码+测试 PASS** | 83 项全绿 |
| P2 CLI / limits / resource bounds | FAIL | **代码+测试 PASS** | 映射测试存在且通过 |
| Live smoke | NOT RUN | NOT RUN | 仍需用户显式联网授权 |

---

## 7. 下一步指令（PR-1 关闭后）

PR-1 已验收通过。建议按以下顺序推进：

### 7.1 可选（PR-1 完整度，非 gate）

1. **Live smoke**（需用户显式联网授权）：独立 `HOUCHEN_DATA_ROOT` temp、1–3 公开视频、subtitle-only、结束后 `find` 证明无媒体文件；证据写入 handoff 或 `reviews/`。
2. **Git 化 PR-1 成果**：当前 houchen 实现与测试仍为 untracked；在用户要求时按 conventional commit 提交（建议单独 PR：`feat: houchen PR-1 corpus foundation`）。

### 7.2 PR-2 启动前

3. 阅读 `CLAUDE_CODE_IMPLEMENTATION_BRIEF.md` PR-2 范围（normalizer / 文本标准化层）；**不得**在未获新验收前实现 analyzer/publisher。
4. 将 `data/store.db` 新基线 SHA 记入后续验收轮次的红线表（替代 R2 的 `38328cd0…`）。
5. 继续遵守：8 实现文件上限（或按 brief 调整）、不修改三份 Codex 基线文档、研究库 `HOUCHEN_DATA_ROOT` 隔离。

### 7.3 宏观侧（与 PR-1 无关，运维建议）

6. 考虑为 `data/store.db` 增加 launchd 前快照或纳入备份策略，避免未来验收因 scheduled macro run 再次触发 re-baseline 争议。

---

## 8. 最终判定

**PASS。PR-1（Hou Chen Corpus Foundation）验收通过。**

- **Functional**：R2 §5/§6 全部 P0/P1/P2 有代码落点 + 触发测试；192/192 scripts 测试通过。
- **Red-line**：接受 `data/store.db` SHA `52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7` 为新基线（用户 2026-08-24 授权；§9 溯源成立）。
- **Outstanding**：live smoke 未执行（非本轮 FAIL 原因）。
- **可进入 PR-2** 规划与实施。
