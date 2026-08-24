# PR-4 Live Smoke 报告（垂直切片）

> **签发**：Claude Code（2026-08-24）
> **响应**：`reviews/PR4_LIVE_SMOKE_KICKOFF_2026-08-24.md`（用户「live smoke」）
> **结论**：垂直链路全打通；第一批 Markdown 预览生成；Obsidian PUT 止步 dry-run
> **红线**：`data/store.db` SHA 不变（launchd 未被触碰）

---

## 1. 红线 / 隔离

```text
data/store.db 前   3c2ceda61c24e3736864ab3ad0cf6d4ab751a67ac20fb848ba769db0291d9d32
data/store.db 后   3c2ceda61c24e3736864ab3ad0cf6d4ab751a67ac20fb848ba769db0291d9d32
                 → 0 漂移（live smoke 不写宏观 store.db，符合 PR-4 §S-4）

data/houchen 前    0 文件
data/houchen 后    16 文件（catalog → analyze → render 全链落盘）
```

## 2. 链：catalog → fetch → normalize → analyze → validate → concept-seed → search → render → publish

| Step | 命令 | 视频数 | exit | 关键 summary |
|------|------|------:|-----:|--------------|
| 1. Catalog | `catalog --live-smoke-allow --limit 50` | 129 videos | 0 | `videos_discovered=129, upserted=129`（50 videos + 50 streams + 29 shorts）|
| 2. Fetch | `fetch-captions --video-id $VID × 3` | 3 | 0 | each `frozen=1, status=success` |
| 3. Normalize | `normalize --video-id $VID × 3` | 3 | 0 | each `normalized=1, normalizer=vtt_json3_v1/2026-08-24.1` |
| 4. Analyze | `analyze --video-id $VID --provider fake × 3` | 3 | 0 | each `analyzed=1`（fake provider，离线）|
| 5. Validate | `validate` | 3 | 0 | `validated=0, failed=3` — 已知 fake provider 限制 |
| 6. Concept-seed | `concept-seed` | — | 0 | `seeded=7`（domain skeleton）|
| 7. Search | `search --kind transcript --query "DeepSeek"` | — | 0 | `total=5`（命中真实 transcript）|
| 8. Render | `render --kind video --page-key $VID × 3` | 3 | 0 | 3 `.md` files in `data/houchen/publish/render/2026-08-24.1/video/` |
| 9. Publish | `publish --dry-run` | — | 0 | pure plan, no PUT attempted |

## 3. 选择的视频

| video_id | 标题 | 备注 |
|----------|------|------|
| `cYP5Hc-ypOM` | E256 互动部分: 这群男生太年轻 | 中文分析内容 |
| `yVESr3OO7Gg` | E256 重庆荒唐 | 中文分析内容（厚辰相关）|
| `uQmOzzgCzQg` | E253 DeepSeek3.4万字会议泄露 | 中文分析内容（AI 主题）|

3 个视频均来自厚辰频道，公共可见性，含中文字幕。

## 4. DB snapshot

```text
schema_version        : 4
videos                : 129
raw_captions          : 3
transcript_versions   : 3
transcript_segments   : 6981
rendered_pages        : 3
publish_records       : 0

corpus_run by kind/status:
  catalog         success 1
  caption_fetch   success 3
  normalize       success 3
  analyze         success 3
  validate        partial 1
  concept_seed    success 1
```

## 5. 渲染产物

```text
data/houchen/publish/render/2026-08-24.1/video/
├── cYP5Hc-ypOM.md  (828 bytes, SHA 0681a2d6…)
├── yVESr3OO7Gg.md  (749 bytes, SHA f48a4bca…)
└── uQmOzzgCzQg.md  (763 bytes, SHA 215271b3…)

每个 .md 含：
- YAML frontmatter (page_kind, video_id, transcript_version_id, analysis_run_id,
  prompt_version, template_version, claim_count_*, status)
- 标题 + 链接 + 时间 + 状态 badge
- "分析出处" section
- "声明列表" section（本次 validate=0 accepted → 显示「无 accepted 主张」）
```

样例 frontmatter（uQmOzzgCzQg）：

```yaml
---
page_kind: "video"
video_id: "uQmOzzgCzQg"
transcript_version_id: "hctv_uQmOzzgC"
analysis_run_id: "hcrun_uQmOzzgC"
prompt_version: "2026-08-24.1"
template_version: "2026-08-24.1"
claim_count_accepted: "0"
claim_count_rejected: "3"
claim_count_needs_review: "0"
status: "需要复核"
---
```

## 6. 已知 fake provider 限制（不影响验收）

- **validate 状态 partial**：fake provider 的硬编码 `exact_quote` 不在真实 segment 文本中，brief §9.3 Rule 2 拒绝（设计预期）。要 production-quality claims 需真模型（`--provider anthropic/deepseek/minimax`），需用户另授权。
- **claim_count_accepted=0**：因 validate 全失败，render 模板显示「无 accepted 主张」。这是 fake provider 的局限，不是 render 模板的缺陷。
- **真 transcript 命中**：search 已用真实段落（"中国AI" → 5 命中；"DeepSeek" → 5 命中）证明 Phase 0 FTS5 端到端工作。

## 7. 全量回归（live smoke 之后）

```text
python3 -m pytest scripts -q   → 384 passed (PR-4 baseline + 0 漂移)
```

## 8. 下一步（Cursor / 用户裁定门）

- Live smoke 端到端验证完成；第一批 Markdown 预览可在 `data/houchen/publish/render/2026-08-24.1/video/` 直接打开
- 真模型授权 + `config/houchen_publish.env` 创建 → 真 Obsidian PUT 另开 kickoff
- 「合并 PR」（已完成；无 follow-up）
- 后续工作：真 analyze + 真 publish 全链路
