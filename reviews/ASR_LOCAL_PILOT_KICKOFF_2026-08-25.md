# Claude Code — 本地 ASR 试点（3 streams，忽略 shorts）

> **签发**：Cursor（2026-08-25）  
> **触发**：用户「shorts 都是长视频切片，请忽略全部 shorts。asr 可以试点」  
> **前置**：若 `CONCEPT_INCREMENTAL_REFRESH` 尚未交卷，**先做完概念页再开本工单**（不要问用户）  
> **不问用户**；交卷 → `WAIT_CURSOR`

---

## 用户摘要

- **忽略全部 shorts**（切片，不抓、不 ASR、不 analyze、不 publish）  
- 本地 **faster-whisper** 试点 **3 支 streams**（零 LLM token 用于转写）  
- 对照已有 WPS：`Z1HWDoSaC5Q` / `-9qyfgyKkaU` / `ScbTzleF3Pc`（**不要重转**）

### 试点 ID（无字幕 streams）

```text
epg0aoUbPN4   # LIVE 101
E9uJV2bwzjM   # LIVE 100
jfXAn1dgkyw   # LIVE 099
```

---

## 上下文纪律

报告只用 video_id、计数、SHA、时长、segment 数、WER 抽检结论。  
**禁止**贴转写正文 / 完整 title / 音频路径以外的媒体内容。

---

## 0. 同步与红线

```bash
cd /Users/kjonekong/macro-pipeline
git pull
STORE=$(shasum -a 256 data/store.db | awk '{print $1}')
echo "$STORE"   # expect 4a8e409b…
```

| 红线 | |
|------|--|
| `store.db` SHA 前后不变 | |
| **零 shorts**（collection `shorts` 任何 ID） | |
| 不重转 3 支 WPS | |
| 不弱化 validator | |
| 转写 **零** DeepSeek token；analyze 仅上述 3 ID | |
| `HOUCHEN_DATA_ROOT` 勿指到 `asr/audio/**` | |
| 勿 rebuild / 全库 analyze | |

---

## 1. 最小实现（必做）

允许 `pip install faster-whisper`（本机 CPU；**禁止**为 GPU 改系统）。模型默认 **`small`**。

新增（尽量少文件）：

| 文件 | 作用 |
|------|------|
| `scripts/asr_transcribe.py` 或 `lib/houchen_asr.py` + CLI | `yt-dlp` 抽音频 → faster-whisper → VTT 或 segments |
| `scripts/test_houchen_asr.py` | 解析/幂等/跳过 shorts；**不**真下模型也可 mock |

输出建议：

```text
data/houchen/asr/audio/<video_id>.webm   # 或 opus；可保留供抽检
data/houchen/asr/vtt/<video_id>.vtt      # 供 import-transcript
```

入库：复用已有 CLI（`normalizer` 可用 `wps_import` 路径 **或** 新增 `asr_whisper_v1`——二选一，报告写明）：

```bash
python3 scripts/houchen_pipeline.py import-transcript \
  --video-id "$VID" --from-file data/houchen/asr/vtt/${VID}.vtt
```

若 JSON 更顺手：扩展 import 支持 whisper JSON **或** 先写成 `.vtt`。

**跳过 shorts 硬门：** 任何 CLI 若传入 shorts `video_id` → exit 非 0，测试覆盖。

---

## 2. 跑试点（必做）

对每个 `VID`：

```bash
# extract + transcribe（实现后的命令，名称可调整）
python3 scripts/asr_transcribe.py --video-id "$VID" --model small

python3 scripts/houchen_pipeline.py import-transcript \
  --video-id "$VID" --from-file data/houchen/asr/vtt/${VID}.vtt

python3 scripts/houchen_pipeline.py analyze \
  --no-pending --provider deepseek --video-id "$VID" --live-smoke-allow

python3 scripts/houchen_pipeline.py validate --video-id "$VID"
python3 scripts/houchen_pipeline.py render --kind video --page-key "$VID" --from-db
```

全部 render 后：

```bash
python3 scripts/houchen_pipeline.py publish \
  --kind video --apply --operator-authorized --actor asr-local-pilot
```

某支失败：记 ID + 失败 class，继续下一条。

---

## 3. 质量抽检（必做，勿贴正文）

每视频抽 **约 2 分钟** 对照音频（听 + 看对应段）：

| 项 | 记录 |
|----|------|
| 可用 / 不可用 | 一句话 |
| 时间戳是否大致对齐 | 是/否 |
| 是否建议扩量 | GO / DEFER |

**不要求**精确 WER 数字；主观「可抽取主张」即可。3 支中 **≥2 支 accepted≥1** 视为试点技术 PASS。

---

## 4. 门禁

| 项 | 标准 |
|----|------|
| 3 支入库 | `transcript_version` ok（非 shorts） |
| accepted | ≥2 视频各 ≥1 |
| shorts | 0 新 raw_caption / 0 analyze |
| tests | asr + import 相关绿 |
| store.db | SHA == before |
| 报告 | 无转写正文 |

---

## 5. 交付

| 文件 | |
|------|--|
| `reviews/ASR_LOCAL_PILOT_REPORT_2026-08-25.md` | 每 ID 时长、segs、accepted/rejected、抽检 GO/DEFER |
| HANDOFF 追加 | |
| INBOX | `WAIT_CURSOR` |

代码 commit + push `origin main`。勿提交大音频（`.gitignore` `data/houchen/asr/audio/` 若尚未 ignore）。

---

## 不做

- shorts 任何处理  
- 其余 47 streams 全量 ASR  
- 云端 Whisper API  
- 概念页（应已在前置工单完成）
