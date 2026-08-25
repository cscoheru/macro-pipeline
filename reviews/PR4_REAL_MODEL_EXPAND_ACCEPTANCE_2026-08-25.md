# PR-4 真模型 + 扩视频审验（Cursor）

> **签发**：Cursor（2026-08-25）  
> **对照**：`reviews/PR4_REAL_MODEL_EXPAND_REPORT_2026-08-24.md`  
> **用户触发**：「审验」

---

## 用户摘要

| 维度 | 裁定 |
|------|------|
| **工程链路** | **PASS**（7 视频字幕入库 + 真模型 analyze + Obsidian publish） |
| **主张呈现** | **未达成**（真模型 **0 accepted**；Obsidian 页仍「无 accepted 主张」） |
| **路线 2** | 管道跑通，**产品目标还差一步**（prompt / 校验对齐） |

**一句话**：字幕和分析都跑了很多，但 **DeepSeek 抽出的 269 条候选全部被硬校验器拒绝**；页面上仍看不到真实主张列表。

---

## 1. 独立复验

```text
python3 -m pytest scripts -q     → 386 passed
data/store.db SHA                → 3c2ceda…（无变）
render .md 文件                  → 7
publish_record published         → 7
raw_captions / segments          → 9 / 18815
claim accepted / rejected        → 3 / 269
```

3 条 `accepted` 均为 **fake provider 遗留**（同一句「中央财政需扩大…」），**非** deepseek-chat 产出。

---

## 2. 工单完成度

| 项 | Kickoff 要求 | 实际 |
|----|--------------|------|
| Phase A 真模型重跑 3 视频 | analyze→validate→render→publish | ✅ analyze + publish；validate partial |
| Phase B 扩 5–8 视频 | 全链 | ✅ 6 新视频尝试；**4 成功 publish**；2 跳过 |
| Obsidian 有主张列表 | 期望 accepted > 0 | ❌ 全部页 `claim_count_accepted: 0` |
| re-render + re-publish | 必须 | ✅ 7 页已 publish |
| 红线 | store.db 不变 | ✅ |

### 已 publish 的 7 个 video_id

`cYP5Hc-ypOM`、`yVESr3OO7Gg`、`uQmOzzgCzQg`、`7AAezayi7Js`、`AWxr0xZwKII`、`7DsxtHsOCzA`、`6P607QZsf-M`

### 跳过（报告一致）

| video_id | 原因 |
|----------|------|
| `f_jd_j3eEuE` | DeepSeek `content_filter` |
| `mg_BuWqSL9A` | HTTP 400 |

---

## 3. 为何 Obsidian 仍「无 accepted」

1. **硬校验器**（brief §9.3）：`exact_quote` 必须是 segment 文本的子串；模型常改写引文 → **全拒**。
2. **render 输入**：页上 `claim_count_*` 来自渲染时的 `VideoPage.claims`；当前构建未把 DB 里 3 条 fake accepted 挂进新 `analysis_run_id`，故 frontmatter 仍为 0。
3. **结论**：不是 publish 失败，是 **validate 0 真 accepted + render 未展示既有 claim**。

---

## 4. 技术债（非阻断本审验，但影响下一步）

- `houchen_analyzer` 仍 `import insight_provider`（报告已记；与 PR-4 S-4 白名单范围外）
- `corpus_run` 有 1 条 `analyze|running`（可能中断残留，建议 CC 清理或 finish）

---

## 5. Verdict

**PR-4 REAL-MODEL EXPAND — ENGINEERING ACCEPTED / PRODUCT PARTIAL（Cursor 2026-08-25）。**

- ✅  Worth the wait for **规模**：9 字幕、1.8 万段、7 Obsidian 视频页。
- ❌  **主张归类呈现** 尚未出现：需 **prompt 对齐 §9.3** 或阶段性放宽校验 / 先展示「待复核」候选。

---

## 6. 建议下一步（用户裁定门）

| 你说 | 方向 |
|------|------|
| **对齐 prompt** | 新 kickoff：改 `houchen_analysis_prompt.md` + 单视频试跑，目标 ≥1 real accepted |
| **先看待复核** | render 展示 `needs_review` / rejected 摘要（不先改校验器） |
| **换模型** | anthropic / minimax 试 1 视频对比拒率 |
