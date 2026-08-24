# PR-1 独立验收报告（Codex）

日期：2026-08-23  
结论：**FAIL**  
验收角色：只读审查与验证；未修改任何实现代码  
下一阶段：**不得进入 PR-2**

## 1. 结论摘要

当前实现不能通过 PR-1 验收。

离线测试全部通过：PR-1 定向测试为 67/67，全仓 `scripts` 测试为 159/159。但测试替身没有复现真实 `yt-dlp` 的输入输出契约，并且多个关键测试没有真正触发它们声称覆盖的并发、崩溃、完整性、候选回退和宏观隔离路径。因此，“测试绿色”不能证明生产采集链路可用或冻结数据安全。

以下任一项都足以判定 FAIL：

1. 真实 `yt-dlp` 的频道 JSON、字幕清单、字幕文件名和 JSON3 内容均与当前解析/下载契约不符；真实链路无法完成一次可靠冻结。
2. 并发首次冻结会共享临时文件；内容寻址目标会被覆盖；竞争失败者还可能删除被其他视频引用的永久文件。
3. `catalog` 和 `preflight` 成功返回前没有提交；CLI 关闭连接时会静默回滚。
4. `--dry-run` 仍创建目录和 SQLite 数据库，并可绕过联网授权门禁。
5. 迁移可在错误的既有表结构上写入版本 1，错误宣称迁移成功；两个进程首次迁移也会稳定竞争失败。

## 2. 审查范围

验收基线：

- `docs/厚辰/世界苦茶研究库/CLAUDE_CODE_IMPLEMENTATION_BRIEF.md`
- `docs/厚辰/世界苦茶研究库/CODEX_ACCEPTANCE_PROTOCOL.md`
- `docs/厚辰/世界苦茶研究库/ENGINEERING_TEST_PLAN.md`
- `docs/厚辰/世界苦茶研究库/PR1_HANDOFF.md`

实现与测试：

- `lib/houchen_*.py`
- `scripts/houchen_pipeline.py`
- `scripts/test_houchen_*.py`
- `scripts/houchen_fixtures/*`

没有审查或修改 PR-2 的文本标准化、主题分析、检索和下游研究产物。

## 3. 独立验证证据

### 3.1 自动测试

```text
python3 -m pytest scripts/test_houchen_*.py scripts/test_ledger.py scripts/test_migrations.py -q
67 passed in 3.19s

python3 -m pytest scripts -q
159 passed in 3.08s
```

### 3.2 真实工具契约探针（只读、未下载媒体）

```text
yt-dlp --list-subs --skip-download https://www.youtube.com/watch?v=yVESr3OO7Gg
```

实际 stdout 含 `[youtube]`、`[info]` 等日志行，字幕表包含 `Language / Name / Formats`，格式单元格为逗号分隔列表。当前 `_parse_subs_listing()` 看到以 `[` 开头的输出便尝试把整段当 JSON 数组，立即抛出 `PermanentError`。

已安装 `yt-dlp` 源码也确认：

- `--flat-playlist -J` 输出整个 playlist info object，条目位于 `entries`，不是顶层 JSON 数组。
- 字幕输出名由模板、语言和格式共同生成，例如 `<stem>.zh.vtt`，不是当前代码等待的 `<stem>.vtt`。
- 标准 JSON3 是一个包含 `events[].segs[].utf8` 的顶层对象；当前解析器对该结构计数为零并拒绝。

没有进行视频或音频媒体下载；仓库 `data` 下未发现媒体文件。

### 3.3 可复现负面探针

- `_flat_playlist()` 接收真实形状 `{"entries": [...]}`：抛出 `--flat-playlist output is not a JSON array`。
- `_flat_playlist()` 模拟超时：在异常处理处触发 `NameError: subprocess is not defined`。
- 标准 JSON3 `events/segs`：抛出 `json3 has zero non-empty cues`。
- 对未入库的合法显式 video ID 执行冻结：`sqlite3.IntegrityError: FOREIGN KEY constraint failed`。
- 预建错误结构的 `raw_caption(wrong TEXT)` 后迁移：版本被记为 1，错误表结构仍保留。
- 最新结果为 `missing` 的视频仍被 `pending_only` 选中，会形成永久失败重试风暴。
- `fetch-captions --dry-run`：命令退出 0，但创建了目录和 `houchen.sqlite3`。
- 文件 SQLite 运行 `catalog`/`preflight` 后关闭重开：成功结果和审计记录因未提交而消失。
- 两连接并发首次迁移：版本检查发生在锁外，第二连接发生版本主键冲突。

## 4. 阻断问题

### P0-1：内容寻址文件不具备不可变性，并发可造成正式数据损坏

位置：

- `lib/houchen_paths.py:115`
- `lib/houchen_acquisition.py:545-553`
- `lib/houchen_acquisition.py:603-609`
- `lib/houchen_acquisition.py:622-668`

问题：

- 同一视频、同一格式的所有 worker 共用固定临时路径，worker 会互删、互读或互相 rename。
- `os.rename(tmp_path, target)` 在 POSIX 上会无条件替换既有内容寻址目标。
- 已登记的 raw 只检查数据库行存在，不校验文件存在、类型、路径边界、大小和 SHA。
- 竞争失败者仅比较“本视频 winner”的路径，可能删除正在被另一视频引用的相同内容寻址文件。
- 文件和目录未 `fsync` 就提交数据库；掉电边界可能留下数据库正式行指向未持久化文件。
- 已定义的 `raw_integrity_error` 没有可靠生产路径。

必须修改：

1. 每个 attempt 使用独立、随机、同文件系统的临时目录/文件；禁止按 video ID 清理所谓“陈旧”临时文件。
2. 安装内容寻址目标必须使用 no-replace 语义；若目标已存在，重新计算并验证 SHA/size：相同则复用且不得改变 bytes/mtime，不同则返回 `raw_integrity_error`，绝不覆盖。
3. 竞争失败只清理当前 worker 自己的临时文件，绝不删除任何内容寻址目标。孤儿 GC 保持在 PR-1 范围外。
4. 对已登记 raw 建立统一 `verify_frozen_raw()`：`lstat` 普通文件、canonical containment、size 和 SHA 全部匹配后才允许 `already_frozen`。
5. 按 `file fsync → no-replace install/rename → directory fsync → DB INSERT/COMMIT` 排序；任一 I/O 失败不得写入 raw 行。

验收测试：

- 两个独立进程/连接加 barrier，真正同时首次冻结同一视频；严格一方 success、一方 skipped/already_frozen，无 traceback、无锁错误、无临时残留。
- 预先让第三视频引用竞争失败者可能生成的目标；竞争结束后第三视频 bytes、mtime、inode 和 SHA 均保持不变。
- 覆盖正确孤儿复用、错误目标拒绝覆盖、已登记文件删除/篡改/symlink，以及 file/directory fsync 注入失败。

### P0-2：数据根目录和派生路径可通过符号链接逃逸，宏观系统隔离不成立

位置：

- `scripts/houchen_pipeline.py:89-102`
- `lib/houchen_store.py:40-66`

问题：`abspath` 不解析或拒绝 symlink。root、captions 目录或 DB 文件若为 symlink，采集、迁移和只读命令都可能写到 research root 外，包括受保护的宏观目录。

必须修改：

1. 集中校验 data root：canonicalize，逐级 `lstat`，拒绝 symlink，并用 `commonpath` 验证全部派生路径 containment。
2. 明确拒绝宏观系统受保护 roots；DB leaf 也必须拒绝 symlink。
3. `status`/`coverage` 使用真正只读连接，不得先创建目录或执行迁移。

验收测试：root symlink、captions symlink、DB symlink、环境变量覆盖和指向宏观目录的 data root 均在任何写入前失败；外部 sentinel 和宏观目录哈希不变。

### P0-3：错误详情未经脱敏便持久化和展示

位置：

- `lib/houchen_acquisition.py:131-135`
- `lib/houchen_acquisition.py:720-737`

问题：`_truncate_stderr()` 只截断字符串，不清除签名 URL、cookie、Authorization/token 或本机绝对路径。这些内容会进入 SQLite、run summary、异常和 CLI 输出。

必须修改：建立唯一错误清洗入口；先限制原始采集字节，再分类并脱敏，所有持久化和展示只能使用清洗结果。测试必须证明 CLI、异常、`corpus_run`、`corpus_attempt` 都不含秘密原值。

### P1-1：真实 `yt-dlp` 契约与 fake 不一致，主链路不可用

位置：

- `lib/houchen_runner.py:194-217`
- `lib/houchen_acquisition.py:216-263`
- `lib/houchen_acquisition.py:367-402`
- `lib/houchen_acquisition.py:430-468`
- `scripts/houchen_fixtures/fake_ytdlp.py`

必须修改：

1. 使用稳定的结构化 info JSON 读取 playlist、`subtitles` 和 `automatic_captions`；不要解析面向人的 `--list-subs` 表格。
2. 正确读取 playlist object 的 `entries`，并对无效/缺失条目做有界、可观测处理。
3. fake 必须复现真实 `yt-dlp` 的 JSON 和输出文件命名；新增去敏后的真实输出 contract fixtures。
4. 下载到当前 attempt 的唯一临时目录，确定性发现并验证唯一的 `<stem>.<language>.<format>` 产物；不允许模糊 glob 到其他 attempt。
5. JSON3 支持标准 `events[].segs[].utf8`，并保留 VTT 的最小结构验证。
6. 获得用户联网许可后，执行 1–3 个公开视频的 subtitle-only live smoke，验证无媒体文件、raw provenance 完整且重跑无副作用。

### P1-2：`catalog`/`preflight` 成功但没有持久化，且网络期间持有写事务

位置：

- `lib/houchen_runner.py:90-114`
- `lib/houchen_runner.py:142-191`
- `lib/houchen_acquisition.py:578-653`

问题：

- `preflight` 和 `catalog` 写入后不提交；CLI `close()` 会回滚，日志却已打印 success/partial。
- 首个 attempt 写入开启隐式写事务，随后在网络下载期间一直持锁；第二 worker 会在 5 秒 busy timeout 后失败。
- `commit()` 的 `OperationalError` 被吞掉，进一步掩盖持久化故障。

必须修改：

1. preflight 使用明确短事务，并在成功返回或错误重抛前提交审计终态。
2. catalog 按单视频或有界批次提交 `video + membership`，最后单独提交 run 终态；某 tab/条目失败时保留已成功项并提交 partial/gap 证据。
3. 网络和文件 I/O 前结束 attempt 短事务；raw 竞争使用独立的短 `BEGIN IMMEDIATE`。
4. 禁止吞掉事务错误；转成可诊断、可重试且已提交的 run/attempt 结果。

验收测试：必须通过真正的 CLI 子进程运行，进程退出后只读重开文件 SQLite 验证 run、video、collection、membership 和 attempt 均存在；中途失败时已成功批次仍在。

### P1-3：迁移能错误宣称成功，且并发首次迁移不安全

位置：`lib/houchen_migrations.py:43-78` 与 `lib/houchen_schema.py` 的 `CREATE TABLE IF NOT EXISTS` DDL。

问题：错误的既有同名表会被保留，但版本仍推进至 1。另有 version 检查先于 `BEGIN IMMEDIATE`，两个首次迁移者都可读到 0，第二个最终发生版本主键冲突。

必须修改：

1. 只有目标表、列、索引和 triggers 与 v1 精确匹配时才能记录版本 1。
2. 把锁内版本复查和 DDL 放入明确事务；只把“同一 migration 已由竞争者完整完成且 schema 验证通过”视为成功，其他 IntegrityError 必须重抛。
3. 失败迁移不得留下半张表或版本行。

验收测试：错误预建表不推进版本；非法 DDL 全回滚；100 轮两个独立连接同时打开新库均成功，最终版本行严格为 `[1]`。

### P1-4：dry-run 仍写磁盘，并绕过联网授权

位置：

- `scripts/houchen_pipeline.py:89-102`
- `scripts/houchen_pipeline.py:122-166`

问题：CLI 在判断 dry-run 业务逻辑之前总会 `ensure_dirs()`、打开 SQLite 并迁移。`dry_run` 还被当作真实网络授权的替代条件。

必须修改：

1. dry-run 从进程启动到结束不得创建/修改目录、DB、raw、mtime 或环境外状态；使用内存规划或真正的只读路径。
2. dry-run 只表示“不持久化”，绝不代表用户已授权联网；真实 backend 没有 `--live-smoke-allow` 必须拒绝。
3. 生产 CLI 不应接受任意 Python `--runner` 作为“离线证明”；测试应注入 callable，或仅允许 canonical path/hash 固定的 repo fixture 且拒绝 symlink。

验收测试：对全新路径和既有研究库分别做 before/after 树、SHA、mtime 对比；dry-run 无授权时 backend 调用次数严格为零。

### P1-5：状态机、pending 和 coverage 语义错误

位置：

- `lib/houchen_runner.py:411-424`
- `lib/houchen_status.py:142-202`
- `lib/houchen_acquisition.py:582-588`

问题：

- pending 仅以“没有 raw 行”判断，`missing`、`auth_required`、`unavailable`、`permanent_error` 都会被重复选择。
- inventory 失败记录在 `subtitle_inventory` stage，但 status/coverage/recent errors 只读取 `freeze` stage，于是实际认证或工具错误会显示为 pending。
- oldest pending 同样把所有未冻结视频算作 pending。
- catalog partial 只在返回 summary 中可见，持久化 coverage 没有可靠的失败 tab/gap 指标。

必须修改：建立单一、持久化的“每视频最新终态”语义。默认 pending 只能包含未尝试或明确 retryable 的视频；永久/缺失/认证/不可用仅在显式 override 时重试。status、coverage、runner selection 和 oldest pending 必须使用同一查询或同一状态视图。

验收测试：从生产入口制造每一种 outcome，关闭并重开 DB 后同时核对 selection、status、coverage、recent errors 和 oldest pending；默认连续运行不得形成 retry storm。

### P1-6：显式未入库 video ID 触发 FK traceback

位置：

- `lib/houchen_acquisition.py:555-565`
- `lib/houchen_acquisition.py:720-737`

问题：合法格式但不在 `video` 表的 ID 会直接写 `corpus_attempt`，违反 FK；上层 run 可能留在 `running`。

必须修改：在创建 run/attempt 前验证 catalog membership，或设计不违反 FK 的可审计错误表达；CLI 返回结构化非零退出码，run 必须提交 failed 终态。

### P1-7：关键测试为“同名但未触发”，fake 的调用日志也不是观测日志

位置：`scripts/test_houchen_acquisition.py`、`scripts/test_houchen_macro_isolation.py`、`scripts/houchen_fixtures/fake_ytdlp.py`。

问题：

- 所谓并发测试是 A 完全结束后再运行 B。
- 崩溃恢复、已登记 raw 完整性检查并无相应生产断言。
- 手动字幕替换重跑测试没有真正替换场景。
- fallback 测试没有让第一候选失败；生产代码遇到 `tool_error` 会立即 break。
- `calls.jsonl` 是预先定义的 response 脚本，不是 fake 实际收到的 argv；“无媒体下载”和“下载次数”断言检查的是定义，不是观察。
- macro isolation 的“full run”只调用 `run_catalog(tabs=[])`，没有执行 catalog/fetch/raw/CLI；默认测试还依赖本机真实 `yt-dlp --version`。

必须修改：fake 将每次收到的 argv、cwd、时间和结果写入独立 observed-call log；response script 与 observed log 分离。所有关键测试必须先证明相应分支确实被触发，再断言最终状态。

## 5. 重要但非单独阻断的问题

### P2-1：超时分支自身抛出 NameError

`lib/houchen_runner.py:202` 使用 `subprocess.TimeoutExpired` 却没有导入 `subprocess`。补导入并增加 catalog 单 tab 超时后仍持久化 partial 的 CLI 回归测试。

### P2-2：CLI 契约不完整

- partial 与 success 都返回 0；应提供稳定、文档化的不同退出码。
- catalog 的 `--limit` 被解析但没有传入/生效。
- `status`/`coverage` 会创建目录和迁移数据库，不是真正只读。

### P2-3：工具预检与资源上限不足

- preflight 未拒绝空版本、明显过旧版本或当前真实输出中的缺失 JS runtime 警告。
- stdout/stderr 通过 `subprocess.run(...PIPE)` 无界读入内存，截断发生在资源已经消耗之后。
- 字幕大小在子进程完成写盘后才检查，无法阻止磁盘被写满。
- fetch 在批次入口 preflight 一次后，每个视频又执行一次 `yt-dlp --version`，637 个视频会产生约 638 次版本子进程。

应改为有界增量读取，超限立即终止整个子进程组；下载采用受控唯一临时目录并监控配额；一次 run 复用已验证的版本信息。

## 6. 验收矩阵

| 基线能力 | 结果 | 说明 |
|---|---:|---|
| 研究库与宏观系统隔离 | FAIL | symlink/data-root 可逃逸；现有“full run”测试未运行完整链路 |
| append-only migration | FAIL | 错误既有 schema 可推进版本；并发首次迁移冲突 |
| catalog 可恢复、可持久化 | FAIL | 成功返回未 commit；真实 playlist JSON 契约错误 |
| subtitle-only，禁止媒体 | PARTIAL | argv 使用 skip-download，但 observed call log 不真实；未完成生产链路证明 |
| 字幕选择与真实下载 | FAIL | list-subs、输出命名、JSON3 均不兼容真实 yt-dlp |
| raw 永久冻结与 provenance | FAIL | 已登记文件不校验；目标可覆盖/误删；无 durability 顺序 |
| 并发首次冻结 | FAIL | 固定 temp、长写锁、删除共享 target；测试并非并发 |
| retry/no-op rerun | FAIL | permanent/missing 仍被 pending 选择；完整性损坏仍报 already_frozen |
| status/coverage | FAIL | 只看 freeze stage，inventory 失败被误报 pending；partial gap 不可靠 |
| dry-run 无副作用 | FAIL | 实测创建目录和 SQLite；还绕过网络门禁 |
| 错误分类与秘密保护 | FAIL | timeout 分支 NameError；stderr 未脱敏 |
| 离线自动测试 | PASS（证据有限） | 67/67、159/159；fake 与关键场景覆盖不足 |
| live smoke | NOT RUN | 本次只做 list-subs 只读契约探针；未下载字幕或媒体 |

## 7. Claude Code 必须完成的修订顺序

1. 先修 P0：raw no-replace/完整性/并发/durability、路径隔离、错误脱敏。
2. 修真实 `yt-dlp` 结构化契约，并以去敏真实 fixtures 重建 fake。
3. 修 preflight/catalog/fetch 的短事务、终态提交和 catalog partial/gap 持久化。
4. 修迁移的 schema 验证、锁内复查和并发首次打开。
5. 修 dry-run、网络授权、只读 status/coverage 和 runner 注入边界。
6. 统一 pending/status/coverage/retry 状态机，修显式未入库 ID。
7. 重写无效测试，加入真实多进程、进程退出重开、崩溃/完整性和 observed-call 证据。
8. 修完 P2 的 timeout、退出码、limit、preflight、资源上限和重复版本探测。
9. 全量离线测试通过后停止，提交新的 handoff 给 Codex；仍不得进入 PR-2。

Claude Code 不得通过删除或弱化测试、放宽基线、把真实错误标为 skipped，或只修改 `PR1_HANDOFF.md` 来关闭问题。

## 8. 下一轮复验要求

至少提供以下新鲜证据：

```text
python3 -m pytest scripts/test_houchen_*.py scripts/test_ledger.py scripts/test_migrations.py -q
python3 -m pytest scripts -q
```

并单独列出：

- 去敏真实 yt-dlp playlist/info/subtitle/JSON3 contract tests；
- 两进程同时首次迁移 100 轮；
- 两进程同时首次冻结与共享 target 不删除测试；
- raw 删除、篡改、symlink、目标冲突和 fsync 故障测试；
- CLI 子进程退出后重开 DB 的持久化测试；
- dry-run before/after 文件树、SHA、mtime 零变化测试；
- 每种 outcome 的持久化状态机与 no retry storm 测试；
- observed-call log 证明没有音频/视频格式、没有媒体文件；
- 宏观目录全树哈希在完整 PR-1 运行前后不变。

获得用户明确联网许可后，再补充 1–3 个公开视频的 subtitle-only live smoke。live smoke 必须使用独立临时 data root，并在结束后证明不存在媒体文件。

## 9. 最终判定

**FAIL。保留在 PR-1，修完上述问题后重新提交 Codex 独立验收；当前不得进入 PR-2。**
