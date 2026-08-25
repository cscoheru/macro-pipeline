# Claude Code — 外源入库：不明白 EP-230

> **签发**：Cursor（2026-08-25）  
> **触发**：用户「外源入库」  
> **视频**：`KLJJuMybVsc`（不明白播客频道，非世界苦茶编目）  
> **WPS**：`data/houchen/asr/audio/不明白访谈厚辰.docx`  
> **不问用户**；做完继续 `CC_INBOX` 下一件（ASR）

---

## 用户摘要

把嘉宾访谈登记进 houchen 库并导入 WPS，再竖切 analyze。  
**禁止 shorts。** 报告不贴转写正文。

```text
video_id:     KLJJuMybVsc
url:          https://www.youtube.com/watch?v=KLJJuMybVsc
source:       不明白播客 EP-230（2026-08-21）
file:         data/houchen/asr/audio/不明白访谈厚辰.docx
```

重庆 `yVESr3OO7Gg` 已 WPS 入库 — **本工单不要重做、不要重分析**。

---

## 0. 红线

```bash
STORE=$(shasum -a 256 data/store.db | awk '{print $1}')
echo "$STORE"   # 4a8e409b…
```

| | |
|--|--|
| 零写 `store.db` | |
| 不 `catalog` 全频道、不把此 ID 编进 shorts | |
| 插入 `video` 后 **立刻** `import-transcript`（避免 `--pending` 去抓外源自动字幕） | |
| 不中断正在跑的 ASR 单视频；当前条结束后做本工单 | |

---

## 1. 登记 video（必做）

用 **单条** `yt-dlp --skip-download --dump-json` 取元数据，再 `INSERT`（或复用 `houchen_runner` 的 upsert，**不要**跑 `catalog`）。

要求：

- `video_id='KLJJuMybVsc'`
- `canonical_url` = 上表 url
- `channel_handle` 用 dump 的频道（不明白，**不是** `@flipradio_fearnation`）
- `content_kind='video'`（非 short）
- `availability='public'`
- **不要**写入 `video_collection_membership`（避免混入 videos/streams/shorts 集合计数）

幂等：已存在则跳过 INSERT。

---

## 2. 导入 WPS（必做）

```bash
python3 scripts/houchen_pipeline.py import-transcript \
  --video-id KLJJuMybVsc \
  --from-file "data/houchen/asr/audio/不明白访谈厚辰.docx"
```

门禁：`status=success` 或 `already_imported`；segments > 0。

---

## 3. 竖切（必做）

```bash
python3 scripts/houchen_pipeline.py analyze \
  --no-pending --provider deepseek --video-id KLJJuMybVsc --live-smoke-allow
python3 scripts/houchen_pipeline.py validate --video-id KLJJuMybVsc
python3 scripts/houchen_pipeline.py render --kind video --page-key KLJJuMybVsc --from-db
python3 scripts/houchen_pipeline.py publish \
  --kind video --page-id "$(sqlite3 data/houchen/houchen.sqlite3 \
    "SELECT rendered_page_id FROM rendered_page WHERE page_key='KLJJuMybVsc' AND page_kind='video' LIMIT 1")" \
  --apply --operator-authorized --actor guest-bumingbai-ep230
```

若 `--page-id` 不便：`publish --kind video --apply ...` 仅当不会误伤；优先单页。

accepted=0：记拒因计数，仍交卷。

---

## 4. 交付

`reviews/GUEST_BUMINGBAI_EP230_REPORT_2026-08-25.md`：video 行是否新建、segs、accepted/rejected、publish SHA、store SHA。

然后继续 INBOX 的 ASR 试点（若未完成）。全部完 → `WAIT_CURSOR`。
