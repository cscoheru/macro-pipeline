# Claude Code — ASR 扩 5 streams（试点 PASS 后）

> **签发**：Cursor Autopilot（2026-08-25）  
> **前置**：`reviews/ASR_LOCAL_PILOT_REPORT_2026-08-25.md` 技术 PASS（3/3 accepted≥1）  
> **不问用户**；交卷 → `WAIT_CURSOR`

---

## 目标

对 **5** 支无字幕 **streams** 跑与试点相同路径：`asr-transcribe --model small` → import-transcript → analyze → validate → render。全部完成后 `publish --kind video`。

**忽略全部 shorts。** 不重转 WPS 三支与试点三支。

### 本批 ID（按 catalog 新→旧，无 transcript）

```text
7L9X75dL1Dg
TFjqgua7jKk
Xp4GBvKBPww
XUKmvcu9sss
Ft5Xg-Wv52U
```

---

## 纪律

报告只用 video_id、计数、SHA、时长、segment 数、抽检 GO/DEFER。  
**禁止**贴转写正文 / 完整 title。

---

## 红线

| |
|--|
| **单进程** whisper：有 `.lock` 或已有 `asr-transcribe` pid → **禁止**再开 |
| **禁止** `rm` `data/houchen/asr/vtt/*.lock` 或 `*.tmp` 来「重试」 |
| 零 shorts |
| 不重转 `Z1HWDoSaC5Q` `-9qyfgyKkaU` `ScbTzleF3Pc` `epg0aoUbPN4` `E9uJV2bwzjM` `jfXAn1dgkyw` |
| 不写 `data/store.db`（记录 before/after SHA；已漂移也不许「修」） |
| 不弱化 validator；不全库 analyze |
| 转写零 DeepSeek token；analyze 仅上表 5 ID |

巡检：`python3 scripts/cc_autopilot_inspect.py`；约定 `reviews/CC_AUTOPILOT.md`。

---

## 每支 VID（串行）

```bash
python3 scripts/houchen_pipeline.py asr-transcribe --video-id "$VID" --model small
python3 scripts/houchen_pipeline.py import-transcript \
  --video-id "$VID" --from-file "data/houchen/asr/vtt/${VID}.vtt"
python3 scripts/houchen_pipeline.py analyze \
  --no-pending --provider deepseek --video-id "$VID" --live-smoke-allow
python3 scripts/houchen_pipeline.py validate --video-id "$VID"
python3 scripts/houchen_pipeline.py render --kind video --page-key "$VID" --from-db
```

失败：记 ID + error_class，继续下一支。5 支出齐后：

```bash
python3 scripts/houchen_pipeline.py publish \
  --kind video --apply --operator-authorized --actor asr-expand-5
```

---

## 门禁

| 项 | 标准 |
|----|------|
| 入库 | ≥4/5 有 `transcript_version` |
| accepted | ≥3/5 视频各 ≥1 |
| shorts | 0 analyze |
| store.db | SHA 与本工单开始时相同 |
| 报告 | `reviews/ASR_EXPAND5_REPORT_2026-08-25.md` 无转写正文 |

---

## 交付

HANDOFF 追加。INBOX=`WAIT_CURSOR`。commit + push `origin main`（勿提交 `data/houchen/asr/audio/`）。
