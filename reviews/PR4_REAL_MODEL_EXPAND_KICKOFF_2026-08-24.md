# Claude Code — 真模型 + 扩视频

> **签发**：Cursor（2026-08-24）  
> **触发**：用户「真模型，然后扩视频」  
> **前置**：`ObsidianLocalRestWriter` 已接线；live smoke 3 视频已 publish

---

## 用户摘要

两阶段：**A** 用真模型重跑已有 3 视频 analyze→validate→render→publish；**B** 再扩 5–8 个新视频全链。Cursor 已实现 `houchen_analyze.env` + 真 provider 接线。

**用户裁定（2026-08-24）**：在「极简字幕库」与「本工单」之间选择 **继续路线 2**；Obsidian 三页当前仍无 accepted，Phase A 结束必须 re-render + re-publish。

---

## 0. 同步代码

```bash
cd /Users/kjonekong/macro-pipeline
git pull origin main   # 或合并 Cursor/CC 本地 tip（含 houchen_analyze_env + Obsidian PUT 修复）
python3 -m pytest scripts -q   # 应全绿
```

---

## 1. 创建 `config/houchen_analyze.env`

```bash
cp config/houchen_analyze.env.example config/houchen_analyze.env
chmod 600 config/houchen_analyze.env
```

从宏观 `config/insight.env` 复制 key（**勿 commit**）：

```bash
PROVIDER=$(grep '^INSIGHT_PROVIDER=' config/insight.env | cut -d= -f2)
sed -i '' "s/^INSIGHT_PROVIDER=.*/INSIGHT_PROVIDER=${PROVIDER}/" config/houchen_analyze.env
grep -E '^(DEEPSEEK|ANTHROPIC|MINIMAX|INSIGHT_MODEL)' config/insight.env >> config/houchen_analyze.env
```

`INSIGHT_PROVIDER` 必须与下文 `--provider` 一致。

---

## 2. Phase A — 真模型重跑已有 3 视频

已有 ID：`cYP5Hc-ypOM`、`yVESr3OO7Gg`、`uQmOzzgCzQg`

```bash
export PROVIDER=deepseek   # 或 anthropic / minimax，与 env 一致

for VID in cYP5Hc-ypOM yVESr3OO7Gg uQmOzzgCzQg; do
  python3 scripts/houchen_pipeline.py analyze \
    --live-smoke-allow --provider "$PROVIDER" \
    --no-pending --video-id "$VID"
done

python3 scripts/houchen_pipeline.py validate --live-smoke-allow

for VID in cYP5Hc-ypOM yVESr3OO7Gg uQmOzzgCzQg; do
  python3 scripts/houchen_pipeline.py render \
    --kind video --page-key "$VID" --apply
done

python3 scripts/houchen_pipeline.py publish \
  --kind video --apply --operator-authorized --actor real-model-rerun
```

**期望**：`validate` 有 `accepted > 0`；Obsidian 视频页「声明列表」非空。

---

## 3. Phase B — 扩 5–8 个新视频

```bash
# 拉字幕（pending，最多 8 个尚未 fetch 的）
python3 scripts/houchen_pipeline.py fetch-captions \
  --live-smoke-allow --apply --pending --limit 8

python3 scripts/houchen_pipeline.py normalize --apply --pending --limit 8

python3 scripts/houchen_pipeline.py analyze \
  --live-smoke-allow --provider "$PROVIDER" --pending --limit 8

python3 scripts/houchen_pipeline.py validate --live-smoke-allow

# render + publish 所有 video 页（或 --pending 新页）
python3 scripts/houchen_pipeline.py publish \
  --kind video --apply --operator-authorized --actor expand-videos
```

记录 HANDOFF：新 `video_id` 列表、accepted claims 数、vault 路径。

---

## 4. 红线

- 不写 `data/store.db`
- 不读 `config/insight.env` 于运行时（只用 `houchen_analyze.env`）
- 长视频 analyze 可能超时 — 记入 HANDOFF，勿 silent retry 无限循环

---

## 5. 交付

| 动作 | 要求 |
|------|------|
| HANDOFF | Phase A/B 命令、accepted/rejected 计数、Obsidian 路径 |
| 报告 | `reviews/PR4_REAL_MODEL_EXPAND_REPORT_*.md` |
| INBOX | `WAIT_CURSOR` |

---

## 6. 费用提示

真模型按 token 计费；8 视频 × 长字幕可能显著。若单视频失败，跳过并记入 HANDOFF，不要全频道重跑。
