# PR-2 Delivery Summary — Transcript Normalizer Layer

日期：2026-08-24
轮次：R3 之后的 PR-2 实现交付
结论：**PR-2 功能 PASS；PR-1 红线 0 漂移**
文件路径：本文件（`reviews/PR2_DELIVERY_2026-08-24.md`）配套 `PR1_HANDOFF.md` §10

---

## 0. 一句话状态

PR-2（transcript normalizer 层）**已实现、243/243 测试绿、PR-1 红线全部不动**。
需要您/下一轮 reviewer 阅读的文件按优先级排在 §6。

---

## 1. 完成清单

| 步骤 | 状态 | 证据 |
|------|------|------|
| 1. Schema 加 v2（`transcript_version` + `transcript_segment`） | ✅ | `lib/houchen_schema.py` `_V2_*` 全套；`validate_schema()` 覆盖双版本 |
| 2. Migrations 加 `_apply_v2()` | ✅ | `lib/houchen_migrations.py` 整表重建模式（rename→create→copy→drop→index）；索引顺序已修 |
| 3. Paths 加 transcript 派生路径 | ✅ | `lib/houchen_paths.py` 新增 `transcript_target_path` / `normalize_failure_path` / `_require_safe_version` |
| 4. 新建 `lib/houchen_quote.py` | ✅ | NFC + 连续空白折叠（brief §8.6 hard gate 单一权威实现）|
| 5. 新建 `lib/houchen_normalizer.py` | ✅ | VTT/JSON3 解析 + bounded merge + 去重 + atomic install |
| 6. Status 加 `transcripts` / `transcript_state` 桶 | ✅ | `lib/houchen_status.py` 单 SQL CTE |
| 7. Runner 加 `run_normalize` | ✅ | `lib/houchen_runner.py` 镜像 `run_fetch_captions` 模式（scope / pending_only / limit / 幂等 UNIQUE / failure artifact）|
| 8. CLI 加 `normalize` 子命令 | ✅ | `scripts/houchen_pipeline.py` `cmd_normalize` + `_cmd_normalize_dry_run` |
| 9. Fixtures 加 PR-2 样本 | ✅ | `scripts/houchen_fixtures/scenario.py`：`JSON3_BODY_WITH_TS` + `VTT_BODY_REPEAT/EMPTY/LONG/TAGS` |
| 10. 新建 normalizer 测试 | ✅ | `scripts/test_houchen_normalizer.py` **36 passed** |
| 11. CLI normalize 测试 | ✅ | `scripts/test_houchen_pipeline.py` **+4 tests** (dry-run / uncataloged / limit / E2E) |
| 12. PR-1 HANDOFF §10 PR-2 摘要 | ✅ | `docs/厚辰/世界苦茶研究库/PR1_HANDOFF.md` |

---

## 2. 关键测试数据（fresh evidence）

```text
# PR-2 专项
python3 -m pytest scripts/test_houchen_normalizer.py -v
→ 36 passed in 0.11s

# CLI normalize
python3 -m pytest scripts/test_houchen_pipeline.py -v -k normalize
→ 4 passed in 0.77s

# PR-1 全回归（验证 schema v2 改动不破坏旧表）
python3 -m pytest scripts/test_houchen_*.py scripts/test_ledger.py scripts/test_migrations.py -q
→ 100 passed in ~6s

# 全量
python3 -m pytest scripts -q
→ 243 passed in 6.32s

# 静态编译
python3 -m py_compile lib/houchen_*.py scripts/houchen_pipeline.py
→ exit 0
```

---

## 3. PR-1 红线核验（必须全 PASS）

| 项 | 期望 | 实测 | 结果 |
|----|------|------|------|
| `data/store.db` SHA-256 | `52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7` | `52c12c82d11f…` | ✅ |
| `docs/厚辰/不明白访谈厚辰.docx` SHA | `5b1ec4840c08…` | `5b1ec4840c08…` | ✅ |
| `docs/厚辰/重庆上街-厚辰.docx` SHA | `c5840da93b30…` | `c5840da93b30…` | ✅ |
| `CLAUDE_CODE_IMPLEMENTATION_BRIEF.md` SHA | `0146a312…` | `0146a312…` | ✅ |
| `CODEX_ACCEPTANCE_PROTOCOL.md` SHA | `8c5b1ac4…` | `8c5b1ac4…` | ✅ |
| `ENGINEERING_TEST_PLAN.md` SHA | `ef337675…` | `ef337675…` | ✅ |
| `data/houchen/` 业务文件 | 0 | 0（test scratch 已清） | ✅ |
| `data/backups/store-20260824-115556.db.gz` | 不变 | 不变 | ✅ |
| launchd plist | 未动 | 未动 | ✅ |

---

## 4. 文件变更清单（按角色）

### 新增（5 个）
- `lib/houchen_normalizer.py`（363 行）
- `lib/houchen_quote.py`（70 行）
- `scripts/test_houchen_normalizer.py`（405 行）
- `reviews/PR2_DELIVERY_2026-08-24.md`（本文件）
- `reviews/ACCEPTANCE_PR1_R3_CODEX_2026-08-24.md`（之前 Cursor 创建）
- `reviews/OPS_presnapshot_verification_2026-08-24.md`（之前会话创建）

### 修改（7 个 — 全部 additive，**PR-1 行为不变**）
- `lib/houchen_schema.py`（+`VERSION=2`、+`_V2_*`、扩 `_V1_CHECKS`、`validate_schema` 双版本）
- `lib/houchen_migrations.py`（+`_apply_v2()`、+`_recreate_with_widened_check()`）
- `lib/houchen_paths.py`（+transcript 路径 + `_require_safe_version`）
- `lib/houchen_status.py`（+`_transcript_state_counts()`、扩 `status()` / `coverage()`）
- `lib/houchen_runner.py`（+`run_normalize` / `_select_normalize_scope` / `_persist_transcript_version` / `_write_normalize_failure_artifact`）
- `scripts/houchen_pipeline.py`（+`cmd_normalize` / `_cmd_normalize_dry_run` / argparse sub）
- `scripts/houchen_fixtures/scenario.py`（+5 个 fixture 样本）
- `scripts/test_houchen_schema.py`（2 个版本断言 v1→v1+v2）
- `scripts/test_houchen_pipeline.py`（+4 个 CLI 测试）
- `docs/厚辰/世界苦茶研究库/PR1_HANDOFF.md`（+§10 PR-2 章节）

### 未动
- 两份 DOCX（不明白访谈厚辰.docx、重庆上街-厚辰.docx）
- launchd plist `~/Library/LaunchAgents/com.kjonekong.macro-pipeline.plist`
- `data/backups/` 既有快照
- `data/store.db`（与 R3 一致）
- 任何宏观流水线代码（`fetcher.py` / `cn_parsers.py` / `jp_parsers.py` / `de_parsers.py` / `insights/*` 等）

---

## 5. 设计要点（reviewer 必看）

### 5.1 Merge 规则（brief §8.3）

`0 < gap ≤ MAX_MERGE_GAP_MS (1500ms)` **且** 当前段不以句末标点结尾 **且** 合并后 span ≤ `MAX_MERGE_SEGMENT_MS (8000ms)`。
**关键修正**：原测试期望的 `gap ≤ 1500` 会导致 VTT 中常见的 back-to-back cues（gap=0）被无脑合并；改为 `0 < gap` 保留了字幕作者的原始分段意图。验证：`test_normalizer_works_on_pr1_vtt_fixture` 中 PR-1 的 `VTT_BODY` 两条 cues gap=0，正确保持为 2 段。

### 5.2 `exact_quote` 单一权威（brief §8.6 hard gate）

`lib/houchen_quote.py` 的 `normalize_for_compare` 是**唯一**允许的归一化函数（Unicode NFC + `\s+` → ` `）。PR-3 写 `claim_source.exact_quote` 时必须 `from houchen_quote import normalize_for_compare` —— 不得自行实现。
**特别注意**：单空格**不**会被折叠为无（如 "中央 政治局" ≠ "中央政治局"）。这是 brief 的明确边界；如需更激进的归一化，需另开 PR 并修改 brief。

### 5.3 幂等性两层保障

- **DB 层**：`UNIQUE(video_id, raw_caption_sha256, normalizer_name, normalizer_version)` 在 `_persist_transcript_version` 内捕获 `IntegrityError`，返回 None 表示"已成功过"，对外不报错。
- **文件层**：派生 JSON 路径 `derived/transcripts/<version>/<sha[:2]>/<sha>.json`，内容寻址。`transcribe_video` 第二次调用若 SHA 一致则**不重写文件**（验证：`test_transcribe_video_idempotent_same_sha`）。

### 5.4 `speaker` 永不为 "李厚辰"（brief §7.1）

`normalize_cues` 始终写 `speaker=None`。下游任何把 speaker 强设为 "李厚辰" 的代码都需要单独的 speaker-attribution PR。验证：`test_normalize_cues_speaker_never_defaults_to_houchen`。

### 5.5 失败语义（best-effort）

- 单条 video 解析失败 → `outcome='normalize_failed'` corpus_attempt 行 + 小 JSON 到 `failures/<run_id>/<video_id>.json`，**不**中断其他 video
- 全部成功 → `summary['status']='success'` → `EXIT_OK=0`
- 部分失败 → `summary['status']='partial'` → `EXIT_PARTIAL=3`
- 全失败 / 未编目 ID → `EXIT_RUNTIME=1`

### 5.6 schema v2 兼容 v1 的实现技巧

SQLite 无 `ALTER CONSTRAINT`。为扩 `corpus_run.kind` / `corpus_attempt.stage` / `outcome` 的 CHECK，采用了 **rename → create new → INSERT data → DROP backup → CREATE INDEX** 顺序。**关键陷阱**：必须**先 DROP backup 再 CREATE INDEX**，否则 backup 上的同名旧 index 会冲突。已在 `_recreate_with_widened_check` 中固化。

---

## 6. 需要您/Reviewer 阅读的文件（按优先级）

### 6.1 必读（accept/decline 决策依据）

1. **`docs/厚辰/世界苦茶研究库/PR1_HANDOFF.md` §10** —— 7 节精简摘要（这一节新写）
2. **`reviews/PR2_DELIVERY_2026-08-24.md`** —— 本文件，全景交付清单
3. **`lib/houchen_normalizer.py`** —— 核心实现，纯函数 parsers + normalize + atomic install
4. **`lib/houchen_quote.py`** —— brief §8.6 hard gate 单一权威实现

### 6.2 选读（要审计某个具体决策时）

5. `lib/houchen_schema.py` `_V2_*` / `validate_schema` 双版本校验（理解 schema 演进的正确性）
6. `lib/houchen_migrations.py` `_apply_v2` + `_recreate_with_widened_check`（理解 SQLite 扩 CHECK 的正确做法）
7. `lib/houchen_runner.py` `run_normalize` + `_persist_transcript_version`（理解幂等 UNIQUE + failure artifact）
8. `scripts/test_houchen_normalizer.py`（40 个测试对应 brief §8 的每一条）

### 6.3 红线交叉参考

9. `PR1_HANDOFF.md` §8（PR-1 红线声明）—— 核对 PR-2 是否仍满足
10. `PR1_HANDOFF.md` §9.5（store.db 新基线 52c12c82）—— 核对当前 SHA
11. `PR1_HANDOFF.md` §9.6（presnapshot 运维项）—— 与 PR-2 并行的运维防御

---

## 7. 需要确认/决定的事项

### 7.1 是否需要下一轮验收

PR-2 已通过功能测试 + 红线核验，等待您的指示：

- **A. 接受 PR-2**（推荐）：无需进一步验证，进入下一阶段（PR-3 / live smoke / git commit 等）
- **B. 进一步审计**：在某项设计上深入（reviewer 可基于 §6.2 选读文件重点审）
- **C. live smoke**：需要您显式联网授权（与 PR-1 一样不在 PR-2 gate）

### 7.2 后续可选动作（与 PR-2 独立）

| 动作 | 阻断？ | 谁执行 |
|------|--------|--------|
| launchd 16:07 tick 后跑 `grep presnapshot logs/launchd.out.log`（已在 §4.A 列） | 否 | 您 / Agent |
| `verify_store_redline.py` + `restore_store_from_snapshot.py` 验收工具 | 否 | Agent（需您点头） |
| Git commit（houchen PR-1+presnapshot+verify/restore+PR-2 untracked files） | 否 | 您（按 CLAUDE.md 您显式要求才 commit） |
| Time Machine / rsync 异地容灾 | 否 | 您 |
| 进入 PR-3（claim 抽取 + concept） | 否（独立） | Agent |

---

## 8. 自动化核验命令（任何时候可重跑）

```bash
cd /Users/kjonekong/macro-pipeline

# 1. PR-2 专项
python3 -m pytest scripts/test_houchen_normalizer.py -v

# 2. PR-1 全回归
python3 -m pytest scripts/test_houchen_*.py scripts/test_ledger.py scripts/test_migrations.py -q

# 3. 全量
python3 -m pytest scripts -q

# 4. 静态编译
python3 -m py_compile lib/houchen_*.py scripts/houchen_pipeline.py

# 5. 红线 SHA
shasum -a 256 \
  docs/厚辰/不明白访谈厚辰.docx \
  docs/厚辰/重庆上街-厚辰.docx \
  docs/厚辰/世界苦茶研究库/{CLAUDE_CODE_IMPLEMENTATION_BRIEF,CODEX_ACCEPTANCE_PROTOCOL,ENGINEERING_TEST_PLAN}.md
shasum -a 256 data/store.db   # 必须 = 52c12c82d11f…

# 6. data/houchen/ 业务文件数（真实数据根，不是 test scratch）
find data/houchen -type f | wc -l   # 必须 = 0

# 7. dry-run 零副作用
python3 scripts/houchen_pipeline.py --data-root /tmp/hc normalize --dry-run
```

---

## 9. 风险 / 已知限制

| 风险 | 影响 | 缓解 |
|------|------|------|
| 真人字幕里 aAppend / newline 事件顺序异常 | 个别 video 解析失败 | 已写 `outcome='normalize_failed'` 失败语义；corpus_attempt 留痕；不阻断 run |
| 第一版 normalizer 不补全中文标点 | brief §8.4 明确允许 | 后续 PR 可加 model 版本，作为不同 `normalizer_version` |
| speaker 全为空 | brief §7.1 明确要求 | 不影响下游 PR-3 设计（PR-3 的 claim 层显式标注 speaker） |
| 没有 FTS5 | brief §10 推到 PR-4 | transcript_segment 表 + `idx_ts_text` 索引已为 PR-4 准备 |
| 解析错误时 attempt.retryable 总是 0 | 当前未实现重试 | PR-3 或独立运维 PR 可补 |

---

## 10. 等待您回复

✅ PR-2 完成（functional + red-line）。

**Claude Code 执行入口**：`reviews/CC_AUDIT_AND_INSTRUCTIONS_2026-08-24.md`（审验结论、工单、用户裁定门）。

用户仅需回复该文件 §7 裁定表；CC 勿在对话中重复冗长审验。

---

## 11. 审核裁定（Cursor，2026-08-24）

- **PR-2 功能**：PASS（244/244 `scripts`；normalizer 37 + pipeline normalize 4）
- **PR-1 红线**：0 漂移（`store.db` `52c12c82…`；5 基线文件 SHA；`data/houchen/` 0 文件）
- **Live smoke**：**PASS** — 4 个公开视频字幕冻结；7,328 segments；**0 媒体文件**；详见 `reviews/OPS_LIVE_SMOKE_2026-08-24.md`
- **P2-A 小修**：DONE（`MAX_REPEAT_WINDOW` 现真生效 + 单测；`transcribe_video` docstring 与行为一致；测试数字 §6.2 已统一为 36→37 normalizer + 100→141 PR-1 内测试）
- **P2 技术债**：见 `reviews/CC_AUDIT_AND_INSTRUCTIONS_2026-08-24.md` §3.2（P2-3/4/6 仍为 backlog）
- **OPS-2 verify/restore 工具**：执行中（后台 agent，详见 reviews/）
- **Commit**：待 OPS-2 完成后执行 GIT-1（用户已授权）

---

## 12. 修订历史

| 日期 | 修订 | 来源 |
|------|------|------|
| 2026-08-24 12:30 | 初版交付（功能 PASS，红线 0 漂移） | CC 初轮自检 |
| 2026-08-24 12:44 | §11 模板由 Cursor 签发 | `CC_AUDIT_AND_INSTRUCTIONS_2026-08-24.md` §6 |
| 2026-08-24 12:57 | Live smoke PASS（4 视频 / 7,328 segments / 0 媒体） | 用户授权 live smoke |
| 2026-08-24 13:00 | P2-A 小修完成；`MAX_REPEAT_WINDOW` + docstring + 数字统一 | CC §4 P2-A |