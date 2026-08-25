# Claude Code — WPS 三直播：analyze → validate → render → publish

> **签发**：Cursor（2026-08-25）  
> **触发**：用户「WPS 已完成并导入，730 segments 入 FTS；请指引 CC 下一步」  
> **前置**：`wps_import` ×3 已入库（279+244+207=730）；accepted claims=0  
> **不问用户**；交卷 → `WAIT_CURSOR`

---

## 用户摘要

对 **仅下列 3 个** `wps_import` 视频跑通分析竖切并发布到 Obsidian。  
**禁止**全频道 analyze；**禁止**贴转写正文进对话/报告。

```text
Z1HWDoSaC5Q   # 279 segs
-9qyfgyKkaU   # 244 segs
ScbTzleF3Pc   # 207 segs
```

---

## 0. 同步与红线

```bash
cd /Users/kjonekong/macro-pipeline
git pull
STORE_BEFORE=$(shasum -a 256 data/store.db | awk '{print $1}')
echo "$STORE_BEFORE"
```

- `store.db` SHA 前后不变  
- 不弱化 validator / quote  
- 报告只用 video_id、计数、run_id、SHA；**零**字幕/ASR 正文  
- 勿 `HOUCHEN_DATA_ROOT` 指到 `asr/audio/**`  
- 勿 rebuild、勿重下音频、勿重 import（已完成）

---

## 1. 逐视频竖切（必做）

对每个 `VID`：

```bash
python3 scripts/houchen_pipeline.py analyze \
  --no-pending --provider deepseek --video-id "$VID" --live-smoke-allow

python3 scripts/houchen_pipeline.py validate --video-id "$VID"

python3 scripts/houchen_pipeline.py render \
  --kind video --page-key "$VID" --from-db
```

门禁：每个视频 `validate` 的 `validated`（accepted）**≥1** 再 publish；若某条为 0，记拒因占比（R2/R5/… **只写 rule id 与条数**），继续下一条，**不要停问用户**。

全部 render 后：

```bash
python3 scripts/houchen_pipeline.py publish \
  --kind video --apply --operator-authorized --actor wps-stream-pilot
```

（若 CLI 需按 page-id：只发这 3 个 `rp_video_*`。）

---

## 2. 验收

| 项 | 标准 |
|----|------|
| 3× analyze | success（或明确失败 class） |
| accepted | 尽量每视频 ≥1；合计写入报告 |
| Obsidian | `Research/世界苦茶/video/{id}.md` 有主张列表 |
| FTS | 既有 730 segs 仍在；新 claim 可被 search（抽查 1 条 query，勿贴正文） |
| store.db | SHA == before |

---

## 3. 交付

| 文件 | 内容 |
|------|------|
| `reviews/WPS_STREAM_ANALYZE_REPORT_2026-08-25.md` | 每视频 outcome、accepted/rejected、publish SHA |
| HANDOFF 追加 | |
| INBOX | `WAIT_CURSOR` |

本地可 commit 报告；勿 push 除非用户另说。

---

## 不做

- 其余 47 streams / shorts / 全库 analyze  
- whisper / 重下音频 / 重 import  
- PR-5 重做（已完成则跳过）  
