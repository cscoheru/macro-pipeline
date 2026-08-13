# macro-pipeline

宏观经济一手数据源监控 + 自动分析流水线（混合架构）。
配套 Obsidian vault `宏观经济/` 研究体系。详见 vault 内 `宏观经济/研究手册.md`。

## 架构（一句话）
launchd 每日定时跑 `run.py` → 抓取一手源 → 变更检测 → SQLite 存储 + 快照 →
统计 + 框架触发 → 经 **Obsidian REST API** 写入 vault 的 `宏观经济/_pipeline/`
（机器独占命名空间，绕过 TCC）→ macOS 通知。深度解读留 Claude 下次会话读 `待解读/`。

## 目录
```
config/sources.yaml   数据源注册表 + 框架触发规则
config/rest.env       Obsidian REST token+port（600，勿提交）
lib/                  fetcher/detector/store/stats/vault_writer/notify/paths
data/store.db         SQLite 时序库
data/snapshots/<src>/ 原始快照（抓数三件套的"快照"落地）
data/state.json       每源每序列 last_seen（幂等关键）
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
- Phase 3 续：统计局 CPI/PPI/PMI、央行 M2/社融、海关进出口（各一个 parser + 解析失败告警）
- Phase 2：美方 BLS/BEA/FOMC + 跨序列触发规则（如中美背离、M2−CPI）
- Phase 4：launchd 加固（失败重试/通知）+ Claude 侧「读 待解读 → 写解读 → 移 _done」流程（可做 SessionStart hook）

## 前置依赖
- Python 3.14 + pandas/requests/beautifulsoup4/lxml/PyYAML
- Obsidian Local REST API 插件（已启用，token 在 vault `.obsidian/plugins/obsidian-local-rest-api/data.json`）
- 若 Obsidian 未运行 → vault 写入会失败（记日志+通知），但数据仍存本地 SQLite/快照，下次 Obsidian 开启后 `--rebuild` 可补

## 添加一个新源
1. `config/sources.yaml` 加源配置（url/parser/cadence/series）
2. `lib/fetcher.py` 加抓取+解析函数
3. `run.py` 的 `PROCESSORS` 注册 + 写一个 `process_<src>(cfg, state)` 函数
4. 手动 `--source <src>` 验证一轮再纳入定时
