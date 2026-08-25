# 全量字幕语料计划（Full Caption Corpus）

**Date:** 2026-08-25  
**Status:** Plan — Phase 1 执行见 `reviews/CORPUS_EXPAND_KICKOFF_2026-08-25.md`  
**范围:** 编目 **videos + streams**（**忽略全部 shorts**：用户裁定为长视频切片）  
**对照:** brief §5 / §13；§26 A 已做 `videos` 50/50

---

## 1. 现状（2026-08-25）

| 维度 | 计数 |
|------|------|
| 编目 `video` | 129 |
| `raw_caption` | 53（50 YouTube + 3 WPS 人工） |
| `transcript_version ok` | 53（`vtt_json3_v1` 50 + `wps_import` 3） |
| accepted claims | 75（15 视频） |
| 无字幕 | streams 缺口（shorts **不计入目标**） |

| 集合 | 策略 |
|------|------|
| videos | 已 50/50 CC |
| streams | ASR / WPS；YouTube 多为 missing |
| shorts | **忽略**（切片） |

**结论:** 扩语料 = **streams** 本地 ASR（默认）+ 关键 LIVE 的 WPS。

---

## 2. 目标

1. **字幕层:** videos + streams 给出 terminal outcome；**shorts 不计入**。  
2. **可分析层:** `normalize ok` 尽量多；不承诺 100%（直播常无 CC）。  
3. **分析层:** 竖切分批推进（本计划 **不写** 全库 analyze）；见竖切 kickoff。  
4. **红线:** `store.db` 只读；不 whisper 机转写（用户已定 WPS 路径）。

---

## 3. 三轨策略

### 轨 A — YouTube 官方字幕（自动）

```bash
fetch-captions --pending --live-smoke-allow   # 可 --limit 分批
normalize --pending
coverage --markdown
```

- **优先集合:** 仅 `streams`。**禁止** shorts。  
- **预期:** streams 大量 `missing`（直播无自动字幕）— **正常**，记 ID 即可。  
- **批次:** `--limit 20` 循环直至 `pending=0` 或仅 terminal。  
- **禁止:** 本轨完成后立即全库 analyze。

### 轨 B — WPS 人工转写（高价值直播）

已验证路径：`import-transcript --video-id --from-file`（`.txt/.vtt/.srt/.docx`）。

| 项 | 说明 |
|----|------|
| 试点 | 3 streams 已导入（730 segs） |
| 下一批 | 按 **时长/主题** 人工选 5–10 支（用户 WPS，零 token） |
| 入库 | 同 pilot；`analyze` 须 `--video-id`（`wps_import` 不进 `--pending`） |
| 音频 | 仅提取 webm，不 whisper |

**选片原则（文档化，不自动）:** 长直播、宏观/地缘主线、尚无 accepted claims 的 streams。

### 轨 C — 本地 ASR（推荐替代 WPS 扩量）

- **零 LLM token**；成本为 CPU 时间（见 `docs/plans/transcript-alternatives.md`）。  
- `ASR_PREFLIGHT` 已 `GO_PILOT`；3 支 WPS 作质量对照。  
- 执行：`reviews/ASR_LOCAL_PILOT_KICKOFF_2026-08-25.md`（small ×3 streams）。

### 轨 D — WPS 人工（保留，非默认）

- 关键 LIVE、ASR 疑难补洞；不作为批量扩量路径。

---

## 4. 执行分期

| 阶段 | 内容 | 退出 |
|------|------|------|
| **P1** | 轨 A：streams+shorts 全 pending 抓取 + normalize | `pending=0`；coverage 更新 |
| **P2** | 竖切：有 `ok` transcript 未 analyze 的批量 analyze→publish | ≥25 视频有 accepted（或工单 cap） |
| **P3** | 轨 B：用户 WPS 下一批（5–10） | 同 pilot 验收 |
| **P4** | 概念页随 claim 增量 refresh | 挂链概念 re-render |

**不在本计划:** 637 全频道 catalog、PR-6 LLM macro match、Obsidian 公开发布。

---

## 5. 验收指标

| 指标 | P1 后 | P2 后（目标） |
|------|-------|----------------|
| `caption pending` | 0 | 0 |
| `frozen` + WPS | 50+ | 50+ |
| `missing` 登记 | 完整列表 | 稳定 |
| 有 accepted 的视频 | 15 | **≥25** |
| accepted claims | 75 | **≥120** |
| `store.db` SHA | `4a8e409b…` | 不变 |

---

## 6. 报告与文件

| 文件 | 用途 |
|------|------|
| `reviews/HOUCHEN_CAPTION_COVERAGE_*.md` | `coverage --markdown` 快照 |
| `reviews/CORPUS_EXPAND_REPORT_*.md` | 每批 P1+P2 摘要 |
| `reviews/MACRO_BRIDGE_REVIEW_*.md` | macro 人工 review 队列/决议 |

---

## 7. 风险

| 风险 | 缓解 |
|------|------|
| API content_filter | 跳过 ID 列表；不弱化 validator |
| 直播无字幕 | `missing` terminal；走轨 B |
| scan 重复 candidate | PR-5.1 加 dedupe / `reviewed` 工作流 |
| 上下文过滤 | 报告仅 ID/计数/SHA |
