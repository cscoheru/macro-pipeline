# Claude Code — 扩 5 analyze 补跑 + 报告

> **签发**：Cursor Autopilot（2026-08-25 18:58；**19:12 用户选 A** 重试 DeepSeek）  
> **前置**：父 loop `AGENT_EXPAND5_DONE`；5/5 `transcript_version` ok；上次 analyze HTTP 402  
> **不问用户**；交卷 → `WAIT_CURSOR`  
> 若仍 402：记 error_class，**不要死循环重试**，交卷 WAIT_CURSOR

---

## 已完成（勿重做）

| video_id | VTT span_s | segs | tv | accepted |
|----------|-----------:|-----:|:--:|---------:|
| `7L9X75dL1Dg` | — | 3683 | ok | 0 |
| `TFjqgua7jKk` | 8598 | 4109 | ok | 0 |
| `Xp4GBvKBPww` | 10912 | 6008 | ok | 0 |
| `XUKmvcu9sss` | 7498 | 3007 | ok | 0 |
| `Ft5Xg-Wv52U` | 6501 | 3318 | ok | 0 |

`store.db` 仍 `0c0cfbc5cb524f03ef6a208cef4b60b55731afcc360f848d7115e57e3d090a27`。  
**禁止** `asr-transcribe`。**禁止**重 import（除非 tv 缺失）。**禁止**写 `store.db`。零 shorts。

Python 用 **`/usr/local/bin/python3`**。analyze 读 `config/houchen_analyze.env`（已存在，勿打印密钥）。

---

## 每支 VID（串行）

```bash
PY=/usr/local/bin/python3
$PY scripts/houchen_pipeline.py analyze \
  --no-pending --provider deepseek --video-id "$VID" --live-smoke-allow
$PY scripts/houchen_pipeline.py validate --video-id "$VID"
$PY scripts/houchen_pipeline.py render --kind video --page-key "$VID" --from-db
```

IDs：`7L9X75dL1Dg` `TFjqgua7jKk` `Xp4GBvKBPww` `XUKmvcu9sss` `Ft5Xg-Wv52U`

全部后：

```bash
$PY scripts/houchen_pipeline.py publish \
  --kind video --apply --operator-authorized --actor asr-expand-5
```

抽检 GO/DEFER（勿贴正文）→ `reviews/ASR_EXPAND5_REPORT_2026-08-25.md`

---

## 门禁

| 项 | 标准 |
|----|------|
| 入库 | 5/5 `transcript_version`（已满足） |
| accepted | ≥3/5 视频各 ≥1 |
| shorts | 0 analyze |
| store.db | SHA 仍 `0c0cfbc5…` |
| 报告 | 无转写正文 |

HANDOFF 追加。INBOX=`WAIT_CURSOR`。commit+push（勿提交 `data/` 音频）。
