# Claude Code — ASR 再扩 5 streams（本地，零 DeepSeek）

> **签发**：Cursor（2026-08-25 21:46）  
> **触发**：用户「按计划推进 CC，卡住才停」  
> **卡住点**：DeepSeek 花费 → **本工单禁止 analyze**  
> **不问用户**；交卷 → `WAIT_CURSOR`

字幕 `pending=0`；`videos` 集合已全部有 transcript。下一批是 **无字幕 streams**，只做本地 whisper。

## ID（streams，无 transcript_version）

```text
bJYsb-kFdvI
5fsVqcDBFic
3UamnjBEm4E
vWBT_3DaCu8
A5axQwdZchk
```

忽略 shorts。不重转 WPS/试点/扩 5 已完成 ID。

## 纪律

报告只用 video_id、计数、SHA、时长、segment 数、抽检 GO/DEFER。禁止贴转写正文。

Python：`/usr/local/bin/python3`（homebrew python 缺 yaml）。

音频：`data/houchen/asr/audio/<id>.webm` 已有则跳过下载。否则：

```bash
yt-dlp -f ba -o "data/houchen/asr/audio/%(id)s.%(ext)s" -- "https://www.youtube.com/watch?v=$VID"
```

不要 `yt-dlp -x`（需要 ffmpeg PATH）。`houchen_asr` 可直接吃 webm。

## 每支（串行）

有 `asr-transcribe` pid → **禁止**再开。禁止 `rm` lock/tmp。

扩 5 已完成 ID 的 `.lock` 可能还在磁盘（VTT 已落盘、`asr_n=0`）。那是 leftover 文件，不是活锁；**不要 rm**，也不要因此拒开新 ID。新 ID 各自 flock。

```bash
PY=/usr/local/bin/python3
$PY scripts/houchen_pipeline.py asr-transcribe --video-id "$VID" --model small
$PY scripts/houchen_pipeline.py import-transcript \
  --video-id "$VID" --from-file "data/houchen/asr/vtt/${VID}.vtt"
$PY scripts/houchen_pipeline.py render --kind video --page-key "$VID" --from-db
```

**禁止** `analyze` / `--provider deepseek`。

5 支出齐后：

```bash
$PY scripts/houchen_pipeline.py publish \
  --kind video --apply --operator-authorized --actor asr-expand-5b
```

## 门禁

| 项 | 标准 |
|----|------|
| 入库 | ≥4/5 `transcript_version` |
| analyze | 0 次 DeepSeek |
| shorts | 0 |
| store.db | SHA 前后相同（现 `0c0cfbc5…`） |
| 报告 | `reviews/ASR_EXPAND5B_REPORT_2026-08-25.md` 无转写正文 |

HANDOFF 追加。INBOX=`WAIT_CURSOR`。commit+push（勿提交 `data/` 音频）。
