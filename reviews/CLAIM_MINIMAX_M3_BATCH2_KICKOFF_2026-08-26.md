# Claude Code — MiniMax-M3 抽 claim（第 2 批 5 streams）

> **签发**：Cursor（2026-08-26 16:45）  
> **前序**：`reviews/CLAIM_MINIMAX_M3_BATCH1_REPORT_2026-08-26.md`（analyze 5/5；accepted 19）  
> **不问用户**；交卷 → `WAIT_CURSOR`

## ID（streams，有 transcript、无 claim 行）

```text
3UamnjBEm4E
vWBT_3DaCu8
A5axQwdZchk
2zyAnqllesM
19Xb-C7Rwkk
```

忽略 shorts。禁止 `asr-transcribe`。禁止 DeepSeek。不准写 `data/store.db`。不重跑 batch1 ID。

已有 `houchen_pipeline.py analyze` pid → **禁止**再开第二路。

## 纪律

报告只用 video_id、计数、run_id、SHA、accepted/rejected、拒因 rule id。禁止贴转写正文、禁止贴 API key。

Python：`/usr/local/bin/python3`。analyze 读 `config/houchen_analyze.env`（minimax / MiniMax-M3）。勿打印密钥。

validate 退出码 3（`partial`）**不是失败**：记下 accepted/rejected 后继续 render。只有 analyze 非 0 才 `continue` 跳过该支。

## 每支（串行）

```bash
PY=/usr/local/bin/python3
$PY scripts/houchen_pipeline.py analyze \
  --no-pending --provider minimax --video-id "$VID" --live-smoke-allow
$PY scripts/houchen_pipeline.py validate --video-id "$VID" --live-smoke-allow || true
$PY scripts/houchen_pipeline.py render \
  --kind video --page-key "$VID" --from-db --live-smoke-allow
```

5 支出齐后写 `reviews/CLAIM_MINIMAX_M3_BATCH2_REPORT_2026-08-26.md`。

## 门禁

| 项 | 标准 |
|----|------|
| provider | 仅 minimax / MiniMax-M3；0 次 DeepSeek |
| shorts / ASR | 0 |
| store.db | SHA 前后相同（现 `b57ce29f…`）；漂移只记录，不修复 |
| 报告 | 无转写正文、无密钥 |

HANDOFF 追加。INBOX=`WAIT_CURSOR`。commit+push（勿提交 `config/houchen_analyze.env`）。
