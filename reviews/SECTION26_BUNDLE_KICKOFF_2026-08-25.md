# Claude Code — §26 三件套（分期执行）

> **签发**：Cursor（2026-08-25）  
> **触发**：用户短词「全量字幕 / PR-5 / ASR」  
> **原则**：按 brief 顺序推进；**不问用户**；本工单**禁止**全频道 637 analyze

---

## 用户摘要

三阶段一次做完能做的，然后 `WAIT_CURSOR`：

| 阶段 | 做什么 | 不做 |
|------|--------|------|
| **A 全量字幕** | catalog 刷新（可选）+ `fetch-captions --pending` 全 pending + `normalize --pending` + coverage | 不对 637 跑 analyze/validate |
| **B ASR** | **仅预研报告**（brief §5.3 硬门） | 不下模型、不装 GPU 依赖、不下载音视频 |
| **C PR-5** | 写 `docs/plans/pr5-macro-bridge.md` 计划 | 不写实现代码（等 Cursor 审计划） |

---

## 0. 同步

```bash
cd /Users/kjonekong/macro-pipeline
git pull
STORE_BEFORE=$(shasum -a 256 data/store.db | awk '{print $1}')
echo "$STORE_BEFORE"
```

---

## A — 全量字幕抓取（必做）

现状约：`video≈129`，`raw_caption≈14`。目标：对 **pending** 尽量抓完中文字幕并 normalize。

```bash
# 可选：刷新编目（若 catalog 过旧）
python3 scripts/houchen_pipeline.py catalog --live-smoke-allow

# 全量 pending 字幕（可分段 limit，但要覆盖完 pending；允许过夜）
python3 scripts/houchen_pipeline.py fetch-captions --pending --live-smoke-allow

# 规范化所有新建 raw
python3 scripts/houchen_pipeline.py normalize --pending

# 覆盖报告
python3 scripts/houchen_pipeline.py coverage --markdown | tee reviews/HOUCHEN_CAPTION_COVERAGE_2026-08-25.md
python3 scripts/houchen_pipeline.py status
```

**允许**：`--limit` 分批循环直到 pending=0 或仅剩 terminal。  
**禁止**：`analyze` / `validate` 扫全库；单次 analyze 批量 >12。

交付写入总报告：

- frozen / missing / unavailable / retryable / auth_required 计数
- store.db SHA 仍 = before
- 跳过/永久失败样例 ID

---

## B — ASR 预研（必做，无实现）

brief §5.3：启用 ASR 前必须先提交缺口比例、价值抽样、成本、媒体保留、验收标准；**首版不得下载模型/媒体或加 GPU 依赖**。

写：`reviews/ASR_PREFLIGHT_2026-08-25.md`，至少含：

1. `caption_missing`（及无中文字幕）占比与绝对数（来自 status/coverage）
2. 抽样 5–10 个 missing 视频：title、是否值得 ASR（分析线 vs Short/杂项）
3. 候选技术：`faster-whisper`（仅文档引用）；预估磁盘/时长/是否需保留音视频
4. 建议试点规模（例如 3 视频）与验收标准草案
5. **明确建议**：`GO_PILOT` / `DEFER`（带理由）

**禁止**：`pip install` whisper、下载 `.bin`、拉音视频。

---

## C — PR-5 计划（必做，无实现）

写：`docs/plans/pr5-macro-bridge.md`，对照 brief §12 / §16 PR-5：

必须写清：

- 只读打开 `data/store.db` 的方式（URI / 现有只读 API）；**零写**宏观库
- 表/接口草案：`macro_link_candidate`、evaluation + external_evidence
- 关系类型：`supports|challenges|contextualizes|unresolved`（全 candidate）
- CLI/测试矩阵：前后 `store.db` SHA 不变；无来源 macro_bridge 硬拒绝（已有 R8）
- 首版范围：**稳定接口或 JSONL 导出**；不做自动联动写回
- 拟改文件清单（≤8 若可能）与退出条件

**禁止**：改 `lib/` 实现、改宏观 migrations、写 store.db。

---

## 红线（全阶段）

- `data/store.db` SHA before == after
- 不弱化 `houchen_validator` / `houchen_quote`
- 不做全频道 analyze
- 不 push（除非用户另说）
- 日志无 API key

---

## 交付

| 文件 | 内容 |
|------|------|
| `reviews/HOUCHEN_CAPTION_COVERAGE_2026-08-25.md` | A 覆盖 |
| `reviews/ASR_PREFLIGHT_2026-08-25.md` | B 预研 |
| `docs/plans/pr5-macro-bridge.md` | C 计划 |
| `reviews/SECTION26_BUNDLE_REPORT_2026-08-25.md` | 总报告（A/B/C 摘要 + SHA） |
| `reviews/CC_HANDOFF_2026-08-24.md` | 追加 |
| `reviews/CC_INBOX.md` | `WAIT_CURSOR` |

完成后 **停止**。Cursor 审验后会分别开：ASR 试点实现 和/或 PR-5 实现 kickoff。
