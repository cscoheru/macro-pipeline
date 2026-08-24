# PR-1 第二轮独立验收报告（Codex）

日期：2026-08-23  
轮次：R2（针对 `PR1_HANDOFF.md` Resubmission）  
结论：**FAIL**  
下一阶段：**不得进入 PR-2**  
验收方式：只读代码审查、离线测试、临时目录/临时 SQLite 负面探针；未修改实现代码

## 1. 结论摘要

本轮确认 Claude Code 已真实关闭一部分第一轮问题，但 PR-1 仍不能通过。

当前存在 4 个 P0：

1. 生产默认 SQLite 路径会跟随 symlink，可把研究迁移写入 data-root 外的数据库；若指向宏观库，可能直接修改宏观系统。
2. `raw` 等派生目录不做逐组件 symlink 检查，`ensure_dirs()` 可在 data-root 外甚至受保护宏观目录中创建目录。
3. hard-link 不可用时退化为普通 `rename()`，竞态下仍会覆盖内容寻址目标；既有 symlink target 也可能被当作可复用 raw。
4. 目录 fsync 失败被吞掉，函数仍报告安装成功，随后数据库可登记一个未满足掉电持久性保证的文件路径。

另有 catalog/preflight dry-run 写库、schema 伪验证、候选回退、partial gap、SQL N+1 等明确基线违例。因此测试绿色不足以给出 PASS。

## 2. 红线独立核验

用户提交的红线声明经 Codex 独立核验为真：

| 项目 | 结果 | 证据 |
|---|---:|---|
| `data/store.db` 未变化 | PASS | SHA-256 `38328cd0b4fcc328f1ec1448f194668eca2b310c39be50d70476b435a06b9d18` |
| `data/houchen/` 无业务文件 | PASS | `find data/houchen -type f` 为 0 |
| 实现文件上限 | PASS | 8 个实现文件 |
| 两份 DOCX 未修改 | PASS | SHA 分别为 `c5840da9…`、`5b1ec484…`，mtime 保持原值 |
| 三份 Codex 基线文档未修改 | PASS | SHA/mtime 与第一轮验收基线一致 |
| 未进入 PR-2 | PASS | 未发现 PR-2 schema/normalizer/analyzer/publisher 实现 |

红线通过不等于 PR-1 功能验收通过；以下 FAIL 来自实现与验收基线仍不一致。

## 3. Fresh verification

```text
python3 -m pytest scripts/test_houchen_*.py scripts/test_ledger.py scripts/test_migrations.py -q
70 passed in 2.60s

python3 -m pytest scripts -q
162 passed in 2.75s

python3 -m py_compile <8 implementation files>
exit 0
```

专项复验还确认：

- 两连接并发首次迁移 100 轮均成功，最终版本严格为 `[1]`。
- 20 轮真实双连接首次冻结均得到一个 `success` 和一个 `skipped/race_lost`。
- 文件 SQLite 完成 preflight/catalog/fetch 后关闭并只读重开，run/video/raw 均已持久化。
- 在外部 runner 调用期间，第二连接可获得 `BEGIN IMMEDIATE`，未发现跨网络 I/O 的长写锁。
- structured playlist/info、JSON3 `events/segs`、真实字幕命名、observed-call log 和单次版本探测的离线路径已修正。
- status 在 fresh root 上不创建 DB；未发现媒体文件。

## 4. 已关闭的第一轮问题

以下部分不要求 Claude Code 重做，只需确保后续修改不回归：

1. playlist 已从错误的顶层数组契约改为读取 `{"entries": [...]}`。
2. 字幕 inventory 已改为结构化 `subtitles` / `automatic_captions`，不再解析 `--list-subs` 人类表格。
3. JSON3 已支持标准 `events[].segs[].utf8`；字幕输出名包含 language + format。
4. attempt 使用独立 temp 目录；正常 hard-link 路径不会覆盖既有目标。
5. 已登记 raw 会校验 regular file、containment、size 和 SHA 后才返回 `already_frozen`。
6. preflight/catalog/fetch 的正常成功路径会提交终态；catalog 已成功 tab 会持久化。
7. 迁移的锁内 version recheck 与双连接首次迁移已闭环；中途非法 DDL 可整体回滚。
8. observed-call log 已与 response script 分离；当前 fixture 路径没有音视频下载 flags。
9. status/coverage 的 CLI 打开方式已改为 SQLite read-only URI，fresh root 不会建库。
10. URL/Bearer/基础 secret 和绝对路径的现有脱敏测试已通过。

## 5. 仍未关闭的阻断问题

### P0-1：生产默认 DB leaf 未拒绝 symlink，可修改 data-root 外的 SQLite

位置：`lib/houchen_store.py:52-61`

```python
target = db_path or houchen_paths.sqlite_path()
if db_path is None:
    houchen_paths.verify_data_root()
    target = houchen_paths.sqlite_path()
elif os.path.islink(target):
    raise ...
conn = sqlite3.connect(target)
```

`elif` 使默认生产路径完全跳过 DB leaf symlink 检查。

独立探针：

```text
<root>/houchen.sqlite3 -> <outside>/external.sqlite3
houchen_store.connect()
external DB migration version = 1
external file 0 bytes -> SQLite database
```

影响：若 symlink 指向 `data/store.db` 或另一宏观 SQLite，研究迁移会在 root 隔离检查通过后作用于宏观文件，属于实际越界写和数据破坏风险。

必须修改：

1. 默认路径与测试路径在连接前都无条件 `lstat` 拒绝 symlink。
2. 验证父目录组件；在威胁模型需要抵御并发换链时，采用目录 fd + `O_NOFOLLOW`/等价安全打开方式。
3. 失败必须发生在打开 SQLite 之前，外部文件 bytes、SHA、mtime 均不得变化。

回归测试：通过默认无参数 `connect()` 触发 DB symlink 场景，而不是只测试显式 `db_path=`。

### P0-2：派生目录 symlink 未校验，`ensure_dirs()` 可写到研究根之外

位置：

- `lib/houchen_paths.py:74-106`
- `lib/houchen_store.py:30-42`

当前只检查 data-root 叶子是否为 symlink，没有按声明逐级 `lstat`；`ensure_dirs()` 直接对 `raw/captions`、`raw/metadata`、`raw/.tmp` 等调用 `makedirs`。

独立探针：

```text
<root>/raw -> <outside>
ensure_dirs()
<outside>/.tmp, <outside>/captions, <outside>/metadata 被创建
```

另一个探针令配置路径的中间父组件为 symlink，`resolve_data_root()` 正常返回 realpath，没有拒绝。

必须修改：

1. 从 canonical root 向每个派生 leaf 逐组件 `lstat`，拒绝任何 symlink。
2. 最好用 dir fd + no-follow 语义创建目录，避免检查/创建竞态。
3. 在第一项外部写入前完成全部路径验证。

回归测试：覆盖中间 root component、`raw`、`raw/captions`、`raw/.tmp`、DB leaf 分别指向普通外部目录与宏观受保护目录；外部树 SHA/mtime/清单必须不变。

### P0-3：no-replace 的降级路径仍可覆盖竞态目标，并接受 symlink target

位置：`lib/houchen_acquisition.py:499-554`

```python
except OSError:
    if os.path.exists(target):
        ...
    os.rename(src_path, target)
```

普通 POSIX `rename()` 会覆盖在 `exists()` 之后、rename 之前出现的目标。Codex 注入 hard-link 不支持，并在该窗口建立竞争目标；目标被覆盖，函数仍返回 `created=True`。

另一个探针预置一个指向 data-root 内 regular file 的 symlink target，且内容 SHA 相同；`install_content_addressed()` 返回 `(target, False)` 并接受该 symlink。后续 `verify_frozen_raw()` 才会拒绝，导致首次运行可能 success、重跑却 integrity error。

必须修改：

1. 删除普通 rename fallback 并 fail closed；或使用平台真正原子的 `RENAME_NOREPLACE` / `RENAME_EXCL`。
2. 目标存在时先 `lstat`，只允许 regular file；拒绝 symlink 和其他类型。
3. 不得用 `exists + rename` 模拟排他安装。

回归测试：hard-link 不支持 + 竞态目标、预置 symlink target、预置目录/FIFO target；目标 inode、bytes、mtime 均不得变化。

### P0-4：目录 fsync 错误被吞掉，durability 保证不成立

位置：`lib/houchen_acquisition.py:486-496`

```python
except OSError:
    pass
```

Codex 让源文件 fsync 成功、第二次目录 fsync 抛错；`install_content_addressed()` 仍返回 `(target, True)`。调用者随后会 INSERT/COMMIT raw 行。

这与 handoff 声明的 `file fsync → install → directory fsync → DB INSERT/COMMIT` 不一致。

必须修改：

1. 目录 fsync 错误默认向上传播，阻止 raw INSERT。
2. 若某平台确实不支持，必须只识别明确、已验证的 `ENOTSUP`/`EINVAL` 并使用文档化的平台替代方案；不得吞掉全部 `OSError`。
3. 已安装但 DB 未登记的文件可以作为允许的孤儿保留，不能为了“清理”删除可能共享的目标。

回归测试：分别注入 file fsync 和 directory fsync 故障，断言 raw row 不存在；并用调用顺序 spy 验证 DB commit 晚于目录持久化成功。

### P1-1：schema validation 并不“精确”，同名空 trigger 可冒充 frozen guard

位置：`lib/houchen_schema.py:329-360`

当前只比较 table 的列名顺序；index 只看名称和表名；trigger 只看名称。没有验证类型、PK、NOT NULL、DEFAULT、CHECK、FK、index columns/unique 或 trigger body。

独立探针：把 `noguard_upd_raw_caption` 替换为同名 `SELECT 1` 空 trigger：

```text
validate_schema = True
schema_version = 1
UPDATE raw_caption succeeds; language becomes en
```

必须修改：

1. 使用 `table_xinfo`、`foreign_key_list`、`index_list/index_info` 验证完整结构。
2. 比较规范化后的 trigger SQL，至少验证 event、table 和预期 `RAISE(ABORT, ...)` body。
3. 伪 v1 必须拒绝且 version 不前进。

回归测试：同名空 trigger、错误 index column、缺 FK、错误 CHECK/PK/NOT NULL 分别构造，全部必须被拒绝。

### P1-2：dry-run 只修了 fetch；catalog 和 preflight 仍写磁盘

位置：

- `scripts/houchen_pipeline.py:120-153`
- `scripts/houchen_pipeline.py:162-198`

`catalog` 和 `preflight` 都在 dry-run 分流前调用 `_open_write_db()`；preflight 完全忽略 `args.dry_run`。

独立探针：

```text
catalog --dry-run  -> 创建 houchen.sqlite3
preflight --dry-run -> 创建 houchen.sqlite3、raw/*、derived、artifacts、failures
```

这直接违反 implementation brief §14：“支持 `--dry-run` 的命令不得写数据库、文件或 Vault”。

必须修改：所有接受 `--dry-run` 的 subcommand 必须在 `_open_write_db()` 前进入零写路径。若不支持某命令的 dry-run，就不要在 parser 中暴露该 flag，并清楚返回 usage error。

回归测试：fetch/catalog/preflight 的成功和工具失败 dry-run；全新不存在 root 与既有 root 两类；比较目录、文件、SHA、mtime 全部不变。现有 `_tree_state()` 只记录文件，不记录空目录，也必须补齐。

### P1-3：状态与 pending 查询违反明确的 SQL aggregate/no-N+1 基线

位置：

- `lib/houchen_status.py:35-46`
- `lib/houchen_status.py:144-160`
- `lib/houchen_schema.py:368-396`
- `lib/houchen_runner.py:317-333`

`status()` 先取全部 video，再对每个视频查询 raw 和 latest attempt；`oldest_pending` 和 fetch scope 又重复这一过程。100 个 pending 视频的 status 探针记录 208 条 SELECT。

这直接违反 implementation brief §15.1：“coverage/status 使用 SQL 聚合，不逐视频 N+1 查询”，也违反 test plan 的 1,000-row fixed-query-count 要求。

必须修改：用一个公共 CTE/view/window query 计算每视频最新 freeze outcome、raw 状态和 pending；status、coverage、oldest pending、fetch selection 复用它，并在 SQL 层应用 limit。

回归测试：1,000 行 trace callback，查询数必须是固定常数；补 `EXPLAIN QUERY PLAN` 索引断言。

### P1-4：高优先字幕候选的下载失败不会回退到有效候选

位置：`lib/houchen_acquisition.py:820-827`

```python
if e.outcome in (OUT_RETRYABLE, OUT_TOOL_ERROR, OUT_AUTH_REQUIRED,
                 OUT_UNAVAILABLE):
    break
```

负面探针配置“manual json3 下载失败、auto vtt 有效”，结果为 `tool_error`，raw row 为 0；第二候选没有尝试。

这违反 test plan §3.2 的“manual high-priority download invalid + auto valid → freeze auto after recorded candidate failure”。

必须修改：区分全局工具/认证/视频不可用错误与单候选不可下载/无效。候选级失败要记录可观测证据并继续下一候选；只有真正的全局失败才 break。

回归测试：manual download nonzero、empty、malformed 三类分别回退到 auto valid，并断言第一候选错误可见、最终 raw track 为 auto。

### P1-5：catalog partial 的失败 tab/reason 在 coverage 中不可见

位置：`lib/houchen_status.py:136-141`

`_catalog_partial()` 仅返回 `{status: count}`。run 的 `summary_json` 虽包含 tab error，但 coverage 不解析或展示；探针得到的只有 `{'partial': 1}`，没有失败 tab 和原因。

这违反 engineering test plan 的 operator-visible 结果：“failed tab and reason in coverage”。

必须修改：coverage 输出最近/有界的 partial gaps，至少含 run_id、tab、error_class/outcome 和时间；保持 JSON 有界且全部错误详情已脱敏。

### P1-6：所谓 full macro isolation test 不是完整 CLI/磁盘链路

位置：`scripts/test_houchen_macro_isolation.py:187-232`

当前测试使用内存 DB 和模块 API，只 hash `store.db`、insights、snapshots。它没有覆盖实际 CLI、磁盘研究 DB、`state.json`、其他可能宏观 DB、config/logs、发布/Vault 路径和自动任务面；也无法捕获本轮已经复现的生产 DB symlink 问题。

必须修改：以真实 CLI 子进程、磁盘研究 DB 和 canonical fake 跑 `preflight → catalog → fetch → rerun → status → coverage`，对全部受保护路径做文件清单、SHA 和 mtime before/after。

## 6. P2 重要问题

### P2-1：显式未编目 ID 返回进程成功且缺乏可审计 ID

位置：

- `lib/houchen_runner.py:317-320`
- `lib/houchen_acquisition.py:724-731`
- `scripts/houchen_pipeline.py:168-175`

独立 CLI 探针：

```text
fetch-captions --video-id zzzzzzzzzzz
summary: missing=1, status=success
exit code: 0
```

数据库既无该 ID 的 attempt，也没有 run-level missing ID 列表。应在建 run 前拒绝未编目显式 ID，或持久化结构化 run-level failure；CLI 必须非成功退出且不得调用字幕网络端点。

### P2-2：`tool_error` 在 status 中消失，status/coverage 分类不一致

位置：`lib/houchen_status.py:35-70` 与 `scripts/houchen_pipeline.py:105-117`。

唯一视频为 `freeze/tool_error` 时：

```text
status captions: 全部为 0
coverage caption_outcomes: tool_error=1
```

必须显式输出 `tool_error`，或统一折叠到 retryable；所有 caption buckets 总和应等于 video 总数。

### P2-3：stdout/stderr/字幕 byte limits 不是主动资源边界

位置：

- `lib/houchen_acquisition.py:152-221`
- `lib/houchen_acquisition.py:620-644`

stderr 超限后被 unregister 但不继续 drain/kill，子进程会填满 pipe 并最终被误报 timeout。stdout 超限只是静默丢弃；字幕大小只在子进程完成后检查，期间仍可写满临时盘。

独立探针：1 MB stderr、64-byte limit → `TimeoutExpired`；并非明确的 output-limit failure。

必须修改：首次超限立即杀整个进程组并返回稳定 resource-limit error，或继续 discard-drain 且明确标记 overflow；下载需在运行期间执行大小限制并终止子进程。注入 runner 的返回值也必须受相同上限。

### P2-4：负数 `--limit` 被解释为 Python 负切片

位置：

- `lib/houchen_runner.py:159-160,285-286`
- `scripts/houchen_pipeline.py:267,275`

`--limit -1` 返回成功，并从两条中静默处理一条。CLI 与 runner 双层要求 `limit >= 0`；覆盖 `-1/0/1/超大值`。

### P2-5：handoff 中若干测试声明与实际测试不符

- `test_failed_ddl_rolls_back_fully` 没有注入非法 DDL，只重复测试 wrong preexisting table。
- `test_install_content_addressed_fsync_failure_no_install` 只覆盖第一次 file fsync，不覆盖 directory fsync。
- `test_data_root_rejects_symlink_component` 只覆盖 root leaf，不覆盖中间组件。
- `test_db_symlink_rejected` 只覆盖显式 `db_path=`，不覆盖默认生产路径。
- `test_dry_run_zero_filesystem_change` 只覆盖 fetch，且 tree snapshot 不记录空目录。
- `test_timeout_classifies_retryable` 只测试 `classify_exit()`，没有触发 subprocess timeout/overflow。
- 没有 candidate download fallback、oversized JSON/caption、failed-tab-in-coverage、实际 `--limit` 或固定查询数测试。

Handoff 必须按真实测试能力描述，不得把同名但未触发的测试列为已闭环证据。

## 7. 验收矩阵

| 能力 | R1 | R2 | 说明 |
|---|---:|---:|---|
| 红线/范围控制 | PASS | PASS | store、DOCX、基线文档、文件上限、PR 边界均符合 |
| 真实 yt-dlp 结构契约（离线） | FAIL | PASS | playlist/info/JSON3/output naming 已修；live smoke 未运行 |
| 正常事务持久化 | FAIL | PASS | preflight/catalog/fetch 关闭重开可见 |
| 并发首次迁移 | FAIL | PASS | 100 轮双连接成功 |
| 并发首次冻结正常路径 | FAIL | PASS | 20 轮一胜一跳过；fallback/durability 仍有 P0 |
| raw 不覆盖/永久冻结 | FAIL | FAIL | rename fallback、target symlink、directory fsync 仍不安全 |
| data-root/宏观隔离 | FAIL | FAIL | 默认 DB leaf 和 derived symlink 可越界写 |
| dry-run 零副作用 | FAIL | FAIL | 仅 fetch 已修；catalog/preflight 未修 |
| migration 精确验证 | FAIL | FAIL | 名称相同的错误 trigger/FK/index 可冒充 v1 |
| retry/candidate fallback | FAIL | FAIL | 单候选 tool_error 阻止后续有效候选 |
| status/coverage | FAIL | FAIL | N+1、tool_error 遗漏、partial gap 不可见 |
| CLI 错误/limit | FAIL | FAIL | 未编目 ID exit 0；负 limit 静默切片 |
| 资源上限 | FAIL | FAIL | overflow/deadlock/下载中大小限制未闭环 |
| 离线测试 | PASS（证据不足） | PASS（仍有盲区） | 70/70、162/162；上述负面分支缺测 |
| live smoke | NOT RUN | NOT RUN | 不是本轮 FAIL 的唯一原因 |

## 8. Claude Code 修订顺序

1. 先修 4 个 P0：默认 DB leaf no-follow、所有派生目录逐组件 no-follow、真正 no-replace 安装、目录 fsync 失败向上传播。
2. 补全 schema exact validation 与伪 trigger/FK/index/constraint 测试。
3. 统一所有 dry-run 入口，并用完整目录树 snapshot 验证零副作用。
4. 把状态推导改为公共 SQL aggregate/CTE，修 status/coverage/pending/limit。
5. 修候选级 fallback、partial gap 可见性、未编目 ID 非成功与 tool_error 分类。
6. 修主动资源上限和负数 limit。
7. 用真实 CLI + 磁盘研究 DB 重做 macro isolation E2E。
8. 更新 handoff，只声明真正由测试触发的证据；停止并交回 Codex，不得进入 PR-2。

禁止通过弱化基线、删除断言、把异常改成 skipped、把 symlink 风险标为“仅测试环境”，或只修改文档来关闭问题。

## 9. 下一轮最小复验集

除完整 pytest 外，必须单独提交以下 fresh evidence：

- 默认生产 `connect()` 的 DB symlink 外部哈希不变测试；
- root 中间 component 与每个派生目录 symlink no-write 测试；
- hard-link 不支持 + 竞态目标 no-replace 测试；
- symlink/FIFO/directory 目标拒绝测试；
- directory fsync 单独失败且 DB 无 raw row 测试；
- 同名空 trigger、错误 index/FK/CHECK 的 migration 拒绝测试；
- fetch/catalog/preflight 全部 dry-run before/after 完整树测试；
- 1,000-video 固定 SQL query count + query plan 测试；
- manual candidate 失败、auto candidate 成功的真实 fallback 测试；
- coverage 显示 failed tab/reason；
- explicit uncataloged ID 非成功、无字幕网络调用、run-level ID 证据；
- tool_error 在 status/coverage 一致；
- stdout/stderr/caption 实际超限子进程提前终止；
- CLI/API limit `-1/0/1/large`；
- fake-backed 完整 CLI/磁盘 DB macro isolation E2E。

## 10. 最终判定

**FAIL。继续停留在 PR-1；完成上述修订并重新提交 Codex 独立验收之前，不得进入 PR-2。**
