# PR-4 Live Smoke 审验（Cursor）

> **签发**：Cursor（2026-08-24 21:32）  
> **对照**：`reviews/PR4_LIVE_SMOKE_REPORT_2026-08-24.md` ↔ 本地 `data/houchen/`  
> **用户触发**：「请审验」

---

## 用户摘要

| 项 | 结果 |
|----|------|
| **Live smoke** | **PASS** |
| **垂直链路** | catalog → fetch → normalize → analyze → validate → seed → search → render → publish dry-run **全打通** |
| **可读成果** | 3 个视频 Markdown 已生成（见下） |
| **`data/store.db`** | `3c2ceda…`（smoke 前后无变） |
| **测试** | 384 passed（smoke 后） |
| **真模型 / Obsidian PUT** | 未执行（符合 kickoff scope） |

**裁定：PR-4 LIVE SMOKE ACCEPTED。** 第一批研究成果可在本地 Markdown 直接阅读。

---

## 1. 独立复验

```text
data/houchen 文件数              → 16（smoke 后，预期内）
data/store.db SHA                → 3c2ceda61c24…（与报告一致）
python3 -m pytest scripts -q     → 384 passed
视频数 / 段数 / 渲染页           → 129 / 6981 / 3
search "DeepSeek" --limit 3      → total=3，命中 uQmOzzgCzQg 真实字幕
媒体文件 (.mp4/.webm)            → 0
```

---

## 2. 链路逐步核对

| Step | 报告 | Cursor 核验 |
|------|------|-------------|
| catalog | 129 videos, exit 0 | ✅ `corpus_run` catalog success |
| fetch ×3 | frozen=1 ×3 | ✅ 3 raw caption json3 |
| normalize ×3 | normalized=1 ×3 | ✅ 3 derived transcripts + 6981 segments |
| analyze ×3 fake | analyzed=1 ×3 | ✅ 3 analysis artifacts |
| validate | partial, 0 accepted | ✅ `validate\|partial`；9 claim 行（全 rejected，fake 预期） |
| concept-seed | seeded=7 | ✅ 7 `domain` 行（domain skeleton，非 7 concept） |
| search | DeepSeek 命中 | ✅ CLI 返回 3 条 transcript hit |
| render ×3 | 3 .md | ✅ 文件存在且 frontmatter 完整 |
| publish dry-run | no PUT | ✅ `publish_records=0` |

---

## 3. 成果位置（现在就能看）

在 Obsidian 或任意编辑器打开：

```text
data/houchen/publish/render/2026-08-24.1/video/cYP5Hc-ypOM.md
data/houchen/publish/render/2026-08-24.1/video/yVESr3OO7Gg.md
data/houchen/publish/render/2026-08-24.1/video/uQmOzzgCzQg.md
```

样例页含：YouTube 链接、标题、时间、`分析出处`、frontmatter（`claim_count_*`、`status`）。因 fake validate 全拒，**声明列表为空**——硬校验器行为正确，非 render 缺陷。

---

## 4. 已知限制（非阻断）

| 项 | 说明 |
|----|------|
| `claim_count_accepted=0` | fake provider 的 `exact_quote` 不匹配真 segment；§9.3 Rule 2 拒绝 |
| 无 Obsidian vault 页 | `ObsidianLocalRestWriter` 未实现；publish 止步 dry-run |
| `data/houchen/` 非空 | live smoke **故意**落盘；与 PR 验收期「0 文件」不同阶段 |
| 仅 video 页 | concept / forecast 等页未 render（kickoff 只要求 video ×3） |

---

## 5. 红线

| 检查 | 结果 |
|------|------|
| `data/store.db` smoke 前后 | ✅ 无漂移 |
| 宏观产物树 | ✅ 未触碰 |
| 零媒体下载 | ✅ 仅 json3 字幕 |
| 全量回归 | ✅ 384 green |

---

## 6. 下一步（用户裁定门）

| 你说 | 方向 |
|------|------|
| **真模型** | 新 kickoff：`analyze --provider …` + validate 应有 accepted claims |
| **Obsidian PUT** | 新 kickoff：`config/houchen_publish.env` + `ObsidianLocalRestWriter` |
| **扩视频** | 在现有 `data/houchen/` 上继续 fetch/analyze（无需重 catalog） |

---

## 7. Verdict

**PR-4 LIVE SMOKE ACCEPTED（Cursor 2026-08-24）。**

工程垂直切片验证完成；研究库**首次具备可读 Markdown 预览**。
