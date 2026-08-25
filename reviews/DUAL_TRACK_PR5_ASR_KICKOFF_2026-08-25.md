# Claude Code — 「都做」：PR-5 实现 + ASR 试点

> **签发**：Cursor（2026-08-25）  
> **触发**：用户「都做」  
> **顺序**：先 **P1 PR-5**，再 **P2 ASR 试点**（P1 不过测则停，勿开 P2）  
> **不问用户**；交卷 → `WAIT_CURSOR`

---

## 用户摘要

| 阶段 | 交付 | 红线 |
|------|------|------|
| **P1** | 按 `docs/plans/pr5-macro-bridge.md` 落地代码+测试 | `store.db` SHA 前后不变 |
| **P2** | 3 个 streams ASR 试点 → 可进 normalize（及可选 analyze） | 不下全量 50；报告禁贴转写正文 |

---

## 0. 同步

```bash
cd /Users/kjonekong/macro-pipeline
git pull
STORE_BEFORE=$(shasum -a 256 data/store.db | awk '{print $1}')
echo "$STORE_BEFORE"
```

上下文纪律：报告/对话 **只用 video_id + 计数 + SHA**；禁止贴字幕/ASR 全文（防 `data_inspection_failed`）。

---

## P1 — PR-5 Macro Bridge 实现

对照：`docs/plans/pr5-macro-bridge.md`（已审验 PASS）。

### 必做文件（≤8）

| 文件 | 动作 |
|------|------|
| `lib/macro_bridge.py` | 新建：`open_macro_store_readonly`、`find_candidates`、`export_jsonl`、scan |
| `lib/houchen_schema.py` + migrations | `macro_link_candidate` 表（houchen）；走现有 migration 模式 |
| `scripts/houchen_pipeline.py` | `macro-bridge --scan` / `--export` / `--verify-sha` |
| `scripts/test_macro_bridge.py` | 计划 §5 安全+功能（路径用 `scripts/`，非 `tests/`） |
| `config/macro_bridge_keywords.yaml` | 关键词表（可从计划 §3.1 抽出） |

### 硬约束

- store.db：`file:…?mode=ro` + `PRAGMA query_only=ON`
- **禁止**对 store.db 的 INSERT/UPDATE/DELETE
- **禁止**自动 `import_to_evaluation` 写入（计划：需 reviewed=1；首版可只实现函数或省略 CLI）
- 无新 pip 依赖；无 API key
- 扫 **accepted** claims → 写入 houchen `macro_link_candidate` → JSONL 导出到 `data/houchen/` 下

### 验收命令

```bash
python3 -m pytest scripts/test_macro_bridge.py -q
python3 scripts/houchen_pipeline.py macro-bridge --verify-sha
python3 scripts/houchen_pipeline.py macro-bridge --scan
python3 scripts/houchen_pipeline.py macro-bridge --export data/houchen/macro_links.jsonl
test "$(shasum -a 256 data/store.db | awk '{print $1}')" = "$STORE_BEFORE"
```

P1 不过 → **停止**，写报告，勿开 P2。

---

## P2 — ASR 试点（3 streams）

对照：`reviews/ASR_PREFLIGHT_2026-08-25.md`（GO_PILOT）。

### 范围（仅这 3 个，勿扩）

```text
Z1HWDoSaC5Q
-9qyfgyKkaU
ScbTzleF3Pc
```

### 实现要点

1. 音频：`yt-dlp -x --audio-format m4a/mp3`，存 `data/houchen/asr/audio/<video_id>.*`（gitignore 大文件若过大可只留路径约定 + 小样例 fixture）
2. 转写：`faster-whisper` **small**（允许本机 `pip install faster-whisper` **仅开发机**；勿把模型 commit 进 git）
3. 产出：segments JSON → **适配**现有 normalize 入轨（优先生成可被现有 normalizer 消费的中间格式；若需新 `caption_kind`/`source=asr` 字段，最小 schema 变更并测）
4. 幂等：同一 video 不重复烧盘；失败记 outcome，不崩全批
5. 可选：对成功 ASR 的 3 视频 `normalize` → `analyze --provider deepseek --no-pending` → `validate`（单视频）；**analyze 失败不阻断试点**（记入报告）

### 验收（报告字段）

| 项 | 标准 |
|----|------|
| 3 视频均有 ASR artifact 或明确失败 class | 是 |
| 至少 1 视频进入 `transcript_version status=ok` | 是 |
| WER | 人工抽检可记「未做/抽样笔记」；不要求本机算 WER 工具 |
| shorts | **不做** |
| 对话/报告 | **零**转写正文 |

### 禁止

- 50 streams / 29 shorts 全量 ASR
- 把 ASR 文本 `cat` 进终端给模型看
- 提交模型权重或 >50MB 音频进 git（`.gitignore`）

---

## 交付

| 文件 | 内容 |
|------|------|
| `reviews/PR5_IMPL_REPORT_2026-08-25.md` | P1 测试、候选条数、store SHA |
| `reviews/ASR_PILOT_REPORT_2026-08-25.md` | P2 每视频 outcome、路径、是否 normalize/analyze |
| `reviews/DUAL_TRACK_REPORT_2026-08-25.md` | 总摘要 |
| HANDOFF 追加 | |
| INBOX | `WAIT_CURSOR` |

本地可 commit 实现；**勿 push** 除非用户另说（或特性分支）。

---

## 红线总表

- store.db SHA 全程不变  
- 不弱化 validator/quote  
- 不做全频道 analyze  
- 上下文纪律（防 inspection）  
