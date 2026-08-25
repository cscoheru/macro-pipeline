# PR-4 Prompt 对齐 v3 扩量报告

> **执行**：Cursor（2026-08-25）  
> **对照**：`reviews/PR4_PROMPT_ALIGN_V3_KICKOFF_2026-08-25.md` §3  
> **触发**：用户「扩量并commit」

---

## 用户摘要

| 项 | 结果 |
|----|------|
| **范围** | 7 个已 publish 视频（6 条新跑 v3 analyze；`7DsxtHsOCzA` 沿用试跑） |
| **analyze** | 6/6 success（deepseek） |
| **validate** | 全部 validated≥1 |
| **render `--from-db`** | 7 页本地 Markdown 更新 |
| **publish** | 7/7 Obsidian PUT+GET SHA ok |
| **pytest** | 388 passed |
| **store.db SHA** | `4a8e409b7279…`（扩量前后无变） |

---

## 1. 逐视频 validated（本批 analyze run）

| video_id | validated | rejected | 备注 |
|----------|-----------|----------|------|
| `6P607QZsf-M` | 2 | 6 | partial |
| `7AAezayi7Js` | 7 | 0 | success |
| `AWxr0xZwKII` | 3 | 5 | partial |
| `cYP5Hc-ypOM` | 3 | 4 | partial |
| `uQmOzzgCzQg` | 3 | 5 | partial |
| `yVESr3OO7Gg` | 5 | 2 | partial |
| `7DsxtHsOCzA` | — | — | v3 试跑 4 accepted（未重跑 analyze） |

---

## 2. 库内 accepted 合计（real，按 video_id）

| video_id | accepted |
|----------|----------|
| `6P607QZsf-M` | 2 |
| `7AAezayi7Js` | 7 |
| `7DsxtHsOCzA` | 4 |
| `AWxr0xZwKII` | 3 |
| `cYP5Hc-ypOM` | 4 |
| `uQmOzzgCzQg` | 4 |
| `yVESr3OO7Gg` | 6 |
| **合计** | **30** |

（部分视频含早期 fake-provider 遗留 accepted 行；Obsidian 页展示的是**最新 analyze run** 的 accepted。）

---

## 3. Obsidian

前缀：`Research/世界苦茶/video/{video_id}.md`  
全部 7 页 `vault_sha256 == render_sha256`。

---

## 4. 工程附带

- **publish 重发**：`status=published` 且 SHA 变更时重新 PUT（见 `houchen_publisher.publish_page`）。

---

## 5. 红线

- `houchen_validator` / `houchen_quote` 未改动
- `data/store.db` 无漂移（本机 macro 库）
