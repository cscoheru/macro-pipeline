# Claude Code — ASR 再扩 5i streams（本地，零 DeepSeek；最后 5 条）

> **签发**：Cursor（2026-08-26 13:05）  
> **前序**：`reviews/ASR_EXPAND5H_REPORT_2026-08-26.md` 5/5 入库 PASS  
> **不问用户**；交卷 → `WAIT_CURSOR`

## ID（streams，无 transcript_version）

```text
d5GD60u0BNg
FpUouK8Rnqo
H8H_pVRdkKo
5-eCEBFw2lw
8GXfASgyo1A
```

后两条是 LIVE SPECIAL，仍是 streams 集合，不是 shorts。忽略 shorts。不重转已完成 ID。

本批是 catalog 里最后 5 条无 transcript 的 streams。完成后 streams ASR 队列空（shorts 永不做）。

## 纪律

报告只用 video_id、计数、SHA、时长、segment 数、抽检 GO/DEFER。禁止贴转写正文。

Python：`/usr/local/bin/python3`。音频已有则跳过。否则：

```bash
yt-dlp -f ba -o "data/houchen/asr/audio/%(id)s.%(ext)s" -- "https://www.youtube.com/watch?v=$VID"
```

不要 `yt-dlp -x`。

## 每支（串行）

有 `asr-transcribe` pid → **禁止**再开。禁止 `rm` lock/tmp。

已完成批次 leftover `.lock` 不是活锁；不要 rm，也不要因此拒开新 ID。

```bash
PY=/usr/local/bin/python3
$PY scripts/houchen_pipeline.py asr-transcribe --video-id "$VID" --model small
$PY scripts/houchen_pipeline.py import-transcript \
  --video-id "$VID" --from-file "data/houchen/asr/vtt/${VID}.vtt"
```

**禁止** `analyze` / DeepSeek。不要为 render 去 analyze。不准写 `data/store.db`。

5 支出齐后写 `reviews/ASR_EXPAND5I_REPORT_2026-08-26.md`。

## 门禁

| 项 | 标准 |
|----|------|
| 入库 | ≥4/5 `transcript_version` |
| analyze | 0 次 DeepSeek |
| shorts | 0 |
| store.db | SHA 前后相同（现 `07d418dc…`）；漂移只记录，不修复 |
| 报告 | 无转写正文 |

HANDOFF 追加。INBOX=`WAIT_CURSOR`。commit+push（勿提交 `data/` 音频）。
