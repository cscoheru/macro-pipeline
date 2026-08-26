# Claude Code — ASR 5j 补下 `8GXfASgyo1A`（本地，零 DeepSeek）

> **签发**：Cursor（2026-08-26 15:12）  
> **前序**：`reviews/ASR_EXPAND5I_REPORT_2026-08-26.md` 4/5 入库 PASS（`8GXfASgyo1A` 下载 FAIL）  
> **不问用户**；交卷 → `WAIT_CURSOR`

## ID（streams，无 transcript_version）

```text
8GXfASgyo1A
```

LIVE SPECIAL，仍是 streams，不是 shorts。忽略 shorts。不重转已完成 ID。

磁盘上可能有 `data/houchen/asr/audio/8GXfASgyo1A.webm.part`：yt-dlp 续传即可。**禁止** `rm` `.part` / lock / tmp。

这是 catalog 里最后一条无 transcript 的 stream。完成后 streams ASR 队列空（shorts 永不做）。

## 纪律

报告只用 video_id、计数、SHA、时长、segment 数、抽检 GO/DEFER。禁止贴转写正文。

Python：`/usr/local/bin/python3`。完整 `.webm`/`.m4a`/`.mp3` 已有则跳过下载。否则：

```bash
yt-dlp -f ba -o "data/houchen/asr/audio/%(id)s.%(ext)s" -- "https://www.youtube.com/watch?v=$VID"
```

不要 `yt-dlp -x`。

## 每支（串行）

有 `asr-transcribe` pid → **禁止**再开。禁止 `rm` lock/tmp。

```bash
PY=/usr/local/bin/python3
$PY scripts/houchen_pipeline.py asr-transcribe --video-id "$VID" --model small
$PY scripts/houchen_pipeline.py import-transcript \
  --video-id "$VID" --from-file "data/houchen/asr/vtt/${VID}.vtt"
```

**禁止** `analyze` / DeepSeek。不要为 render 去 analyze。不准写 `data/store.db`。

完成后写 `reviews/ASR_EXPAND5J_REPORT_2026-08-26.md`。

## 门禁

| 项 | 标准 |
|----|------|
| 入库 | 1/1 `transcript_version` ok |
| analyze | 0 次 DeepSeek |
| shorts | 0 |
| store.db | SHA 前后相同（现 `07d418dc…`）；漂移只记录，不修复 |
| 报告 | 无转写正文 |

HANDOFF 追加。INBOX=`WAIT_CURSOR`。commit+push（勿提交 `data/` 音频）。
