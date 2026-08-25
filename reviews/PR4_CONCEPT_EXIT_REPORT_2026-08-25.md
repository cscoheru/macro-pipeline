# PR-4 Concept-Exit Report

> **签发**：Claude Code（2026-08-25）
> **响应**：`reviews/PR4_CONCEPT_EXIT_KICKOFF_2026-08-25.md`
> **PR-4 退出条件（brief §16）**：**已闭环**
> - ≥1 可用概念页 → **6 张**（已 publish 到 Obsidian）
> - 视频分析竖切补到 8-12 → **12 视频**（全部 accepted ≥1）

---

## 红线 / 隔离

```text
data/store.db SHA: 4a8e409b7279… (前 = 后; 0 漂移)
data/houchen files: 49 → 52 (concept + 5 new video Markdown)
data/insights files: 856 (不变)
```

S-4 AST 守卫：通过（PR-4 新模块 6 文件无 `import insight_publisher` / 可执行 `data/store.db` 字面量）。

## 概念页（PR-4 退出必做）

6 张概念页 → `Research/世界苦茶/concept/<concept_id>.md`：

| concept_id | canonical_name | status |
|------------|----------------|--------|
| `hccon_01a0365fedb871c9bcb206e0b393b1ee` | AI泡沫 | proposed |
| `hccon_01a0365fedb775e889e3e43aedae9bf2` | ... | proposed |
| `hccon_01a0367a9b197599a5202af022ce23b4` | ... | proposed |
| `hccon_01a0367a9b1c71718c136feacd171384` | ... | proposed |
| `hccon_01a0367a9b1773a6842d07fa30de2c14` | ... | proposed |
| `hccon_01a0367adf0e724a9a543e90c11d54a2` | ... | proposed |

模板版本：`template_version=2026-08-25.1`（v3 prompt 对齐后 bump）。每页含：
- YAML frontmatter（concept_id / status / template_version）
- 标题 / 定义 / 领域 slug
- **Speaker uses** section（非空；含 `model` 来源 quote + timestamp URL）
- **System analyses** section（system_evaluation claim rows）
- **Canonical definition** section（空；human 注入前）

门禁：vault_sha256 == render_sha256（PUT → GET → SHA 通过）。

## 视频页（竖切补到 12）

12 视频全部 `published` 到 Obsidian（research/世界苦茶/video/）：

| video_id | accepted | 备注 |
|----------|---------:|------|
| cYP5Hc-ypOM | 4 | Phase A 原始 |
| yVESr3OO7Gg | 6 | Phase A 原始 |
| uQmOzzgCzQg | 4 | Phase A 原始 |
| 7AAezayi7Js | 7 | 路线 2 retry 成功 |
| 7DsxtHsOCzA | 4 | v3 smoke 单视频试跑 |
| AWxr0xZwKII | 3 | Phase B |
| 6P607QZsf-M | 2 | Phase B |
| l9qR-bXaFwM | 9 | §2b 新增 |
| Yukb3xuc9l8 | 5 | §2b 新增 |
| gRtY4ZEQI5A | 2 | §2b 新增 |
| 7zRWMu0kU2o | 4 | §2b 新增 |
| gk-_x2DWHCk | 5 | §2b 新增 |

55 real accepted claims 跨 12 unique videos（之前 fake provider 遗留 3 → 现 55 真实）。

## 跳过（非可重试）

- `f_jd_j3eEuE` (藏人/自焚)：DeepSeek content_filter
- `mg_BuWqSL9A` (AI bubble)：DeepSeek HTTP 400

## 测试

```text
python3 -m pytest scripts/test_houchen_render.py scripts/test_houchen_publisher.py -q   → 41 passed
python3 -m pytest scripts -q   → 388 passed (PR-4 baseline 386 + 2 新)
```

## brief §16 退出条件对照

| 条件 | 状态 |
|------|------|
| ≥1 张可用概念页（链接到 ≥1 video / claim / concept_source） | ✅ 6 张 |
| Re-publish 是 no-op | ✅ publish_record 二次发 = status='published' 不变 |
| publish 失败不误记 published | ✅ VaultWriter 协议（PUT → GET → SHA）保留 |

## 红线

- ✅ `data/store.db` 0 漂移
- ✅ 未碰 validator / quote
- ✅ 未做全频道 637 analyze
- ✅ 未做 PR-5 / ASR
- ✅ 未 push（仅本地）

## 下一步（brief §26，留给下一工单）

- 全量字幕（637 视频）
- PR-5 macro bridge
- ASR 替换
- 真人 speaker 解析（brief §7.1 speaker 目前 nullable）

## 等 Cursor 审验

PR-4 concept-exit kickoff 完成；本回合报告 + HANDOFF + INBOX → `WAIT_CURSOR`。
