# macro-pipeline

宏观经济一手数据源监控 + 自动分析流水线（混合架构）。
配套 Obsidian vault `宏观经济/` 研究体系。详见 vault 内 `宏观经济/研究手册.md`。

## 架构（一句话）
launchd 每日定时跑 `run.py` → 抓取一手源 → 变更检测 → SQLite 存储 + 快照 →
统计 + 框架触发 → 经 **Obsidian REST API** 写入 vault 的 `宏观经济/_pipeline/`
（机器独占命名空间，绕过 TCC）→ macOS 通知。深度解读留 Claude 下次会话读 `待解读/`。

**可选的自动洞察生成**（feature flag，默认关闭）：采集后在同一 SQLite 事务里为每个
源-发布建立 `queued` 的 GeneratedInsight，再由 runner 调用模型生成有结论/证据/反证/
机制/影响/下一验证点的文章，硬验证通过后幂等发布到 `宏观经济/_pipeline/洞察/`；只有
证据不足、相互矛盾、模型输出不合格或发布失败才进入 `待审/`。详见下文「自动洞察」。

## 目录
```
config/sources.yaml   数据源注册表 + 框架触发规则
config/rest.env       Obsidian REST token+port（600，勿提交）
config/insight.env    洞察生成 ANTHROPIC_API_KEY/模型/超时（600，勿提交；见 insight.env.example）
config/insight_prompt.md / insight_schema.json   版本化提示词与输出 schema
lib/                  fetcher/detector/store/stats/vault_writer/notify/paths
                      + insight_context/provider/validate/render/runner/publisher
data/store.db         SQLite 时序库（含 append-only ledger 与 GeneratedInsight 状态机）
data/snapshots/<src>/ 原始快照（抓数三件套的"快照"落地）
data/insights/        洞察内容寻址产物：facts/(事实包) artifacts/(Markdown) responses/
data/state.json       每源每序列 last_seen + content_sha256（幂等 + 修订检测关键）
logs/pipeline.log     运行日志
run.py                主入口
```

## 常用命令
```bash
# 手动跑全部启用的源
python3 ~/macro-pipeline/run.py

# 只跑某个源
python3 ~/macro-pipeline/run.py --source fred

# 仅从 store 重建 vault 的"最新读数.md"（不抓取；代码改动/强制刷新用）
python3 ~/macro-pipeline/run.py --rebuild

# 自动洞察（默认关闭；需先配好 config/insight.env）
python3 ~/macro-pipeline/run.py --source fred --insights --max-insights 1   # 采集+生成1篇
python3 ~/macro-pipeline/run.py --insights-only                              # 只重试积压队列
python3 ~/macro-pipeline/run.py --no-generate                                # 采集但不生成
python3 ~/macro-pipeline/run.py --insights-status                            # 打印队列摘要后退出

# launchd 管理
launchctl list | grep macro                          # 查状态
launchctl start com.kjonekong.macro-pipeline         # 立即触发一次
launchctl unload ~/Library/LaunchAgents/com.kjonekong.macro-pipeline.plist  # 停
launchctl load -w ~/Library/LaunchAgents/com.kjonekong.macro-pipeline.plist # 启
tail -f ~/macro-pipeline/logs/pipeline.log           # 看日志
```

## 当前覆盖（24 序列）
**美国 (8, FRED CSV)**：FEDFUNDS / CPIAUCSL / PCEPI / PAYEMS / UNRATE / GDPC1 / GFDEBTN / FYFSD
**中国 (16, HTML 发布稿)**：
- `cn_mof` 财政部（7）：一般公共预算收入/支出、中央/地方支出、政府性基金收支、土地出让收入
- `cn_stats_inv` 固投（3）：固定资产投资、基础设施投资、民间投资
- `cn_stats_cpi` / `cn_stats_ppi` / `cn_stats_pmi`：CPI / PPI / 制造业PMI
- `cn_pbc` 央行（3）：M2 / M1 / 社融存量

**触发规则**：
- 单指标 5 条：美失业率>4.5%、美FFR>3.75%；中地方支出<0、基建<0、土地<-20%
- 跨序列 2 条：**M2−CPI>5pp → F1/F4 两阀门**；**M2−M1>3pp → F1 流速下降**（跨序列对缓存最新值评估，仅当某组成序列本轮有新数据时触发）

**延期**：
- `cn_customs` 海关进出口：WAF 是加速乐(JSL JS挑战)。**原理已解**——无头浏览器能过JSL(MCP Playwright 实测拿到统计快讯列表)。已装 Python playwright+Chromium 并实现 `fetch_html_waf`/`discover_latest_release_waf` 基础设施。但**自主集成受阻**：海关整站对 Python Playwright(无头+有头)返回空(39B)，疑似 CDP 自动化检测或反复测试触发 IP 软封锁；MCP 浏览器(会话内)则能过。未接入 sources.yaml(不 ship 当前会失败的源)。后续：低频重试 / Claude 会话内 MCP 取数 / 散文镜像(证券时报·财联社)。
- FOMC 声明/异议票：federalreserve.gov 发现路径有 quirks（FFR 本身已由 FRED 覆盖）

每日 09:07 / 16:07 自动检测；新发布稿（新期次）才触发全流程（幂等）。

## 待办（后续 Phase）
- 自动洞察上线（plans/eager-snacking-micali.md Phase E）：mock provider 全链 E2E → 一个真实低风险 FRED 更新 `--insights-only` 二次幂等验证 → reload launchd；观察至少两个定时周期后再把 `insights.enabled` 切默认。
- run.py 修订门控：把采集门从 `is_new_period` 升级为 `classify`（new/revision/same），同周期 hash 变化触发带 `supersedes_id` 的修订文章（detector 已就绪，待 insights 开启后再接线）。
- 海关进出口：JSL WAF 仍未自主突破（MCP 浏览器可过），待低频重试 / 会话内取数 / 散文镜像。
- FOMC 声明/异议票：federalreserve.gov 发现路径有 quirks（FFR 本身已由 FRED 覆盖）。

## 自动洞察（可选，默认关闭）

把默认产物从「数据转抄简报」升级为「可直接使用的洞察文章」。整体仍受 feature flag 控制
（`config/sources.yaml` 的 `insights.enabled`，默认 `false`），未开启时流水线行为与之前完全一致。

**数据流**：采集 → 同事务建 EvidenceSnapshot/ResearchItem/GeneratedInsight(`queued`) + provenance →
runner 从内容寻址事实包生成结构化结果 → 本地 schema/事实门禁硬验证 → 渲染 Markdown artifact →
幂等发布（PUT → GET 读回核验 sha256 → `published`）。生成成功 ≠ 发布成功。

**状态机**：`queued → generating → ready | needs_review`；`ready → published → superseded`；
可重试技术失败回 `queued`，内容不合格进 `needs_review`。所有新表禁止 UPDATE/DELETE（append-only）。

**安全边界**：
- API key 只从 `config/insight.env`（600）显式读取，不进 launchd plist/日志/ledger/prompt/artifact/vault。
- 自动写入仅限 `宏观经济/_pipeline/`（洞察/、待审/、_done/）；模型不能控制 vault 路径或 SQL。
- 模型只能引用事实包内 Evidence/Claim/Forecast ID；算术、口径、反证、确定性语言由 validator 硬控，失败不发布。
- 采集优先（fail-open）：ledger/模型/Vault 失败都不中断数据采集；任务留在 `queued`/`ready` 等下次重试。

**人工介入**：`待审/<ins_id>.md` 列出失败门禁与事实包摘要；用 `--insights-status` 看队列
（queued/ready/needs_review/published 计数 + 最老积压 + 最近错误类别），用 `--insights-only` 重跑积压。

**回滚**：把 `insights.enabled` 设回 `false` 即恢复只产出原始简报；旧 `write_queue_brief()` 在观察期保留。

## 前置依赖
- Python 3.14 + pandas/requests/beautifulsoup4/lxml/PyYAML
- Obsidian Local REST API 插件（已启用，token 在 vault `.obsidian/plugins/obsidian-local-rest-api/data.json`）
- 若 Obsidian 未运行 → vault 写入会失败（记日志+通知），但数据仍存本地 SQLite/快照，下次 Obsidian 开启后 `--rebuild` 可补

## 添加一个新源
1. `config/sources.yaml` 加源配置（url/parser/cadence/series）
2. `lib/fetcher.py` 加抓取+解析函数
3. `run.py` 的 `PROCESSORS` 注册 + 写一个 `process_<src>(cfg, state)` 函数
4. 手动 `--source <src>` 验证一轮再纳入定时
