# Claude Code — PR-4 Live Smoke（垂直切片）

> **签发**：Cursor（2026-08-24）  
> **触发**：用户说「live smoke」或「跑通垂直切片」  
> **目标**：在 **真实** `data/houchen/` 落第一批数据 + 本地 Markdown 预览（Obsidian PUT 可选）

---

## 用户摘要

这是**第一次看到研究成果**的路径。需要联网 + 用户授权。默认先跑到 **render**（本地 `.md`），Obsidian PUT 需额外 env。

---

## 0. 前置（用户本机）

| 项 | 要求 |
|----|------|
| 网络 | YouTube / yt-dlp 可访问 |
| 授权 | 所有写命令加 `--live-smoke-allow` |
| 数据根 | 默认 `data/houchen/`（**验收后将有文件 — 正常**） |
| Obsidian（可选） | Local REST API + `config/houchen_publish.env` |

---

## 1. 范围（brief 垂直切片）

- **1–3 个公开视频**（用户指定 video_id 或从 catalog 取最近 3 条分析类）
- 链：`catalog` → `fetch-captions` → `normalize` → `analyze`（fake provider 可先）→ `validate` → `concept-seed` → `search`（抽检）→ `render` → `publish --dry-run`

**不在本工单**：全频道、真模型（anthropic/deepseek）、`ObsidianLocalRestWriter` 实现（若缺失则 publish 止步 dry-run）。

---

## 2. 命令模板

```bash
export REPO=/Users/kjonekong/macro-pipeline
cd "$REPO"

# 1. Catalog（联网）
python3 scripts/houchen_pipeline.py catalog --live-smoke-allow --apply --limit 50

# 2. 取 1–3 个 video_id 后 fetch
python3 scripts/houchen_pipeline.py fetch-captions --live-smoke-allow --apply --video-id VIDEO_ID

# 3. Normalize
python3 scripts/houchen_pipeline.py normalize --apply --video-id VIDEO_ID

# 4. Analyze（默认 fake）
python3 scripts/houchen_pipeline.py analyze --apply --video-id VIDEO_ID

# 5. Validate + concept seed
python3 scripts/houchen_pipeline.py validate --apply --video-id VIDEO_ID
python3 scripts/houchen_pipeline.py concept-seed --apply

# 6. 搜索抽检
python3 scripts/houchen_pipeline.py search --kind claim --query "经济" --limit 5

# 7. Render（本地 Markdown）
python3 scripts/houchen_pipeline.py render --kind video --page-key VIDEO_ID --apply

# 8. Publish dry-run
python3 scripts/houchen_pipeline.py publish --dry-run
```

---

## 3. 成果在哪里看

| 层级 | 路径 |
|------|------|
| 数据库 | `data/houchen/houchen.sqlite3` |
| 字幕/分析 | `data/houchen/raw/`、`derived/`、`artifacts/` |
| **Markdown 预览** | `data/houchen/publish/render/<template_version>/.../*.md` |
| Obsidian（若后续实现 PUT） | vault 内 `Research/世界苦茶/` |

---

## 4. 红线

- **禁止** 写 `data/store.db` 或宏观产物树
- live smoke 前后 `shasum data/store.db` 记入 HANDOFF（漂移则标注 launchd，非 smoke 引入）
- `analyze --provider anthropic` 需用户另授「真模型」

---

## 5. 交付

| 动作 | 要求 |
|------|------|
| HANDOFF | 视频列表、各步 exit code、`publish/render` 样例路径、store.db SHA 前后 |
| INBOX | `WAIT_CURSOR` |
| docs | 可选 `reviews/PR4_LIVE_SMOKE_REPORT_*.md` |
