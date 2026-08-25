# 转写路径对比：WPS vs 可控成本替代方案

**Date:** 2026-08-25  
**触发：** 用户「WPS 费时费力；token 可控即可」  
**结论摘要：** **优先本地 ASR 试点**（零 LLM token）→ 有余力再 API ASR 按分钟封顶 → WPS 仅作质量标杆/疑难补洞

---

## 1. 缺口在哪

| 集合 | 无字幕 | 说明 |
|------|--------|------|
| videos | 0 | 已 100% |
| streams | ~47（50−3 WPS） | 直播回放通常无 CC |
| shorts | **忽略** | 用户裁定：全部是长视频切片，不抓/不 ASR/不分析 |

**P1 已跑完：** YouTube `fetch-captions` 对 streams 多为 terminal `missing`——**不是没试，是平台没字幕后轨**。

---

## 2. 四条路（按推荐顺序）

### 方案 A — 先吃尽已有字幕（零转写成本）

- 仍有 **~14** 支 `transcript ok` 但无 accepted → 直接 `analyze` 竖切。  
- **token：** 仅 DeepSeek analyze（已有 `--video-id` / `--limit` 可控）。  
- **不做：** 新转写。

### 方案 B — 本地 faster-whisper（**推荐扩 streams**）

| 项 | 说明 |
|----|------|
| LLM token | **0**（转写不走 DeepSeek） |
| 成本 | CPU 时间；small 模型约 **2–4× 实时**（ASR_PREFLIGHT） |
| 质量 | 中文 medium/large 更好；可与 3 支 WPS 对照 WER |
| 控制 | `--limit N` 仅 streams；**忽略全部 shorts**；`--max-duration-sec` |
| 入库 | 音频 `yt-dlp` → segments JSON → 接 `import-transcript` 或 `normalizer_name=asr_whisper_v1` |

**试点建议：** 3 支新 stream（非已 WPS 的 104/103/102），WER 抽检 <15% 再 `--limit 5` 扩批。

### 方案 C — 云端 ASR API（token/费用可控）

| 服务 | 计费粗算 | 控制手段 |
|------|----------|----------|
| OpenAI Whisper API | ~$0.006/min | 月度预算、`--limit`、只 streams |
| Deepgram / 阿里云等 | 按分钟 | 同左 |

**适用：** 本机太慢或要 large 质量；仍比 WPS 省人力。  
**注意：** 音频上传第三方；敏感内容需你接受合规。

### 方案 D — WPS 人工（保留）

| 优点 | 缺点 |
|------|------|
| 质量最高 | 费时费力、难规模化 |
| 零机转写 token | 3 支试点已验证 `import-transcript` |

**建议定位：** 质量标杆、ASR 疑难补洞、关键 LIVE 精修——**不作为默认扩量路径**。

---

## 3. 不推荐

| 项 | 原因 |
|----|------|
| shorts 任何处理 | 用户 2026-08-25：切片，**永久忽略** |
| 无上限全 50 streams 一夜跑完 | 磁盘 ~1.5–3.75GB 音频 + 数十小时 CPU |
| analyze 全库 | brief 红线；用 `--limit` 分批 |

---

## 4. 与现有代码的衔接

已有：

- `yt-dlp` 音频下载（WPS pilot 用过 webm）
- `import-transcript`（txt/vtt/srt/docx）
- `ASR_PREFLIGHT` → `GO_PILOT`

待落地（PR-5.2，小工单）：

- `scripts/asr_transcribe.py` 或 pipeline 子命令 `asr-transcribe --video-id --model small --limit`
- segments JSON → 与 WPS 同路径进 `transcript_version` + FTS5
- `analyze` 仍须 `--video-id`（非 vtt_json3 pending）

---

## 5. 建议执行顺序

```text
1. 概念页 refresh（P4）
2. 本地 ASR 试点 3 streams        ← 工单 ASR_LOCAL_PILOT_KICKOFF
3. 试点 PASS 后每批 --limit 5 streams
4. WPS 仅关键 LIVE 补洞
```

**用户已批 ASR 试点**（2026-08-25）。shorts 永久排除。
