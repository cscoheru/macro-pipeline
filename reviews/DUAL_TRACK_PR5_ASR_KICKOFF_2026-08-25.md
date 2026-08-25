# Claude Code — 「都做」：PR-5 实现 + 人工转写导入（WPS）

> **签发**：Cursor（2026-08-25）  
> **触发**：用户「都做」；**修订**：用户「音频撰写文字可以让我在 WPS 中转，不需要消耗 token」  
> **顺序**：先 **P1 PR-5**，再 **P2 音频抽取 + WPS 导入通道**（P1 不过测则停）  
> **不问用户**；交卷 → `WAIT_CURSOR`

---

## 用户摘要

| 阶段 | 交付 | 红线 |
|------|------|------|
| **P1** | 按 `docs/plans/pr5-macro-bridge.md` 落地代码+测试 | `store.db` SHA 前后不变 |
| **P2** | 仅 3 streams **下载音频** + **导入 WPS 转写稿** 的最小路径 | **禁止** faster-whisper / 任何机转写 / 烧模型 token |

**转写由用户在 WPS 完成。** Agent 只准备音频文件 + 能把 WPS 导出的文本/字幕送进 normalize 的导入工具。

---

## 0. 同步

```bash
cd /Users/kjonekong/macro-pipeline
git pull
STORE_BEFORE=$(shasum -a 256 data/store.db | awk '{print $1}')
echo "$STORE_BEFORE"
```

上下文纪律：报告/对话 **只用 video_id + 计数 + SHA**；禁止贴字幕/转写全文。

---

## P1 — PR-5 Macro Bridge 实现

对照：`docs/plans/pr5-macro-bridge.md`。

### 必做文件（≤8）

| 文件 | 动作 |
|------|------|
| `lib/macro_bridge.py` | 新建：只读 store、scan、export |
| `lib/houchen_schema.py` + migrations | `macro_link_candidate` |
| `scripts/houchen_pipeline.py` | `macro-bridge --scan/--export/--verify-sha` |
| `scripts/test_macro_bridge.py` | 安全+功能测试 |
| `config/macro_bridge_keywords.yaml` | 关键词表 |

### 验收

```bash
python3 -m pytest scripts/test_macro_bridge.py -q
python3 scripts/houchen_pipeline.py macro-bridge --verify-sha
python3 scripts/houchen_pipeline.py macro-bridge --scan
python3 scripts/houchen_pipeline.py macro-bridge --export data/houchen/macro_links.jsonl
test "$(shasum -a 256 data/store.db | awk '{print $1}')" = "$STORE_BEFORE"
```

P1 不过 → **停止**，勿开 P2。

---

## P2 — 音频给用户 + WPS 稿导入（取代机转写）

### 若已写 `faster-whisper` / `asr_transcribe.py`

**立刻停用并移除或改造成「仅文档说明」**；不得 `pip install faster-whisper`，不得下载模型。

### 范围（仅 3 个，勿扩）

```text
Z1HWDoSaC5Q
-9qyfgyKkaU
ScbTzleF3Pc
```

### P2a — 只抽音频（给用户用 WPS）

```bash
yt-dlp -x --audio-format m4a -o "data/houchen/asr/audio/%(id)s.%(ext)s" -- "VIDEO_ID"
```

报告写明三个文件的**绝对路径**。  
**禁止**：Whisper / 云 ASR / 任何自动转写。

### P2b — 导入通道（代码）

```bash
python3 scripts/houchen_pipeline.py import-transcript \
  --video-id VIDEO_ID \
  --from-file path/to/wps_export.txt
```

支持 `.txt` / `.vtt` / `.srt`（能做几个做几个）。纯文本无时间戳时可整段或均匀切段，报告注明。  
fixture 用假短文本测幂等；**勿**把真实 WPS 稿贴进对话。

用户尚未交稿：完成 P2a 路径 + P2b 代码与测试即可交卷；INBOX 可 `WAIT_USER` 并写「等 WPS 稿后说 **导入**」。

### 禁止

- faster-whisper / Whisper / 云语音  
- 全频道音频  
- 转写正文进模型上下文  

---

## 交付

| 文件 | 内容 |
|------|------|
| `reviews/PR5_IMPL_REPORT_2026-08-25.md` | P1 |
| `reviews/ASR_PILOT_REPORT_2026-08-25.md` | 音频路径 + import CLI；写明无 whisper |
| `reviews/DUAL_TRACK_REPORT_2026-08-25.md` | 总摘要 |
| INBOX | `WAIT_CURSOR` 或等稿时 `WAIT_USER` |

---

## 红线

- store.db SHA 不变  
- 不弱化 validator  
- **零机转写 token/模型**  
- 上下文纪律  
