# Claude Code — MiniMax-M3 抽 claim（首批 5 streams）

> **签发**：Cursor（2026-08-26 16:30）  
> **触发**：用户改用 MiniMax-M3，禁止 DeepSeek  
> **不问用户**；交卷 → `WAIT_CURSOR`

## ID（streams，有 transcript、无 claim）

```text
5-eCEBFw2lw
8GXfASgyo1A
IPOKcXRZfi4
bJYsb-kFdvI
5fsVqcDBFic
```

忽略 shorts。禁止 `asr-transcribe`。禁止 DeepSeek。不准写 `data/store.db`。

## 纪律

报告只用 video_id、计数、run_id、SHA、accepted/rejected。禁止贴转写正文、禁止贴 API key。

Python：`/usr/local/bin/python3`。analyze 读 `config/houchen_analyze.env`（`INSIGHT_PROVIDER=minimax`，`INSIGHT_MODEL=MiniMax-M3`）。勿打印密钥。

## 每支（串行）

```bash
PY=/usr/local/bin/python3
$PY scripts/houchen_pipeline.py analyze \
  --no-pending --provider minimax --video-id "$VID" --live-smoke-allow
$PY scripts/houchen_pipeline.py validate --video-id "$VID" --live-smoke-allow
$PY scripts/houchen_pipeline.py render \
  --kind video --page-key "$VID" --from-db --live-smoke-allow
```

某条 analyze/validate 失败：记 error_class，继续下一条，不要死循环。accepted=0 也继续（记拒因 rule id 与条数），不要停问用户。

5 支出齐后写 `reviews/CLAIM_MINIMAX_M3_BATCH1_REPORT_2026-08-26.md`。

## 门禁

| 项 | 标准 |
|----|------|
| provider | 仅 minimax / MiniMax-M3；0 次 DeepSeek |
| shorts | 0 |
| ASR | 0 次 `asr-transcribe` |
| store.db | SHA 前后相同（现 `07d418dc…`）；漂移只记录，不修复 |
| 报告 | 无转写正文、无密钥 |

HANDOFF 追加。INBOX=`WAIT_CURSOR`。commit+push（勿提交 `config/houchen_analyze.env`）。
