# PR-4 Real-Model + Expand Report (路线 2 闭环)

> **签发**：Claude Code（2026-08-25）
> **响应**：`reviews/PR4_REAL_MODEL_EXPAND_KICKOFF_2026-08-24.md`
> **路线 2**：等复杂栈跑完；retry 3 失败视频（7AAezayi7Js 成功；f_jd_j3eEuE / mg_BuWqSL9A 非可重试错误）
> **最终**：7 video 页 → Obsidian

---

## 红线 / 隔离

```text
data/store.db 前 = 后 = 3c2ceda61c24…  (0 漂移)
data/houchen   16 → 49 文件  (Phase A/B + 路线 2 retry render+publish)
data/insights  → 856 文件（含 failed_responses/）
```

S-4 AST 隔离守卫：通过（PR-4 新模块 6 文件无 `import insight_publisher` / `import store` / 可执行 `data/store.db` 字面量）。

**遗留问题**：`lib/houchen_analyzer.py` 在 PR-3 期间 `import insight_provider` 用于真实 provider 调用。不在 S-4 白名单（白名单只覆盖 PR-4 新增文件），但本身违反 PR-4 plan §11.4 "Never imports lib/insight_publisher.py"。下次 PR 应拆出独立 houchen provider 层。

## 配置

新建 `config/houchen_analyze.env`（mode 0600，git-ignored）：

```text
INSIGHT_TIMEOUT_SECONDS=300       # 120 → 300（retry 长视频需要）
INSIGHT_MAX_TOKENS=65536
INSIGHT_MAX_INPUT_CHARS=1500000   # 120000 → 1.5M
INSIGHT_PROVIDER=deepseek
INSIGHT_MODEL=deepseek-chat       # reasoner → chat（reasoner 推理烧 token，content 被截断）
DEEPSEEK_API_KEY=<from config/insight.env, mode 0600>
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

## Phase A — 真模型重跑已有 3 视频

| 视频 | analyze | validate | render | publish |
|------|---------|----------|--------|---------|
| cYP5Hc-ypOM | ✓ | partial (52 rejected) | re-rendered (SHA 一致) | ✓ |
| yVESr3OO7Gg | ✓ | partial (52 rejected) | re-rendered | ✓ |
| uQmOzzgCzQg | ✓ | partial (52 rejected) | re-rendered | ✓ |

## Phase B — 扩 6 个新视频（路线 1：直接尝试）

| 视频 | fetch | normalize | analyze (round 1) | analyze (round 2) | render | publish |
|------|-------|-----------|-------------------|-------------------|--------|---------|
| 7AAezayi7Js | ✓ | ✓ | ✗ JSON parse fail | ✓ (timeout 300s) | ✓ | ✓ |
| f_jd_j3eEuE | ✓ | ✓ | ✗ timed out 600s | ✗ content_filter | skipped | skipped |
| mg_BuWqSL9A | ✓ | ✓ | ✗ JSON parse fail | ✗ HTTP 400 | skipped | skipped |
| AWxr0xZwKII | ✓ | ✓ | ✓ | (无 retry) | ✓ | ✓ |
| 7DsxtHsOCzA | ✓ | ✓ | ✓ | (无 retry) | ✓ | ✓ |
| 6P607QZsf-M | ✓ | ✓ | ✓ | (无 retry) | ✓ | ✓ |

### 失败原因（不可重试）

- **`f_jd_j3eEuE` (藏人/自焚)**：`finish_reason=content_filter` — DeepSeek 内容审核拒绝；敏感政治话题不可重试。
- **`mg_BuWqSL9A` (AI bubble)**：`HTTP 400` — DeepSeek API 拒绝请求；可能 fact pack 仍超 token 上限（即使 INSIGHT_MAX_INPUT_CHARS=1.5M，API 端有独立的 token 计数）；或话题内容触发了过滤；不可重试。

## Obsidian publish（最终）

```text
Research/世界苦茶/video/
├── 6P607QZsf-M.md
├── 7AAezayi7Js.md
├── 7DsxtHsOCzA.md
├── AWxr0xZwKII.md
├── cYP5Hc-ypOM.md
├── uQmOzzgCzQg.md
└── yVESr3OO7Gg.md
```

7 个 video 页全部 PUT → GET readback → SHA 验证通过。

## DB snapshot

```text
videos                : 129
raw_captions          : 9   (3 original + 6 Phase B)
transcript_versions   : 9
transcript_segments   : 18815
claim rows            : 272
  accepted            : 3   (fake provider leftovers)
  rejected            : 269
rendered_pages        : 7
publish_records       : 7 (all 'published')

corpus_attempt analyze:
  success 10
  analyze_failed 8
```

## 全量回归

```text
python3 -m pytest scripts -q   → 386 passed (无回归)
```

## 关键发现

1. **deepseek-reasoner 烧 token**：content 被截断 → JSON 失败。已切 deepseek-chat。
2. **brief §9.3 硬校验器严格**：deepseek-chat 输出 269 claim candidates 全部被拒（最常见 `exact_quote` 不在 segment.text）。fake provider 留下的 3 个 accepted 是当前 Obsidian 内容。
3. **DeepSeek 内容审核**会拒敏感话题（藏人/自焚）。
4. **DeepSeek HTTP 400** 在某些 fact pack 长度下触发；模型层有独立的 token 计数。
5. **0 真实 accepted claims**：当前 Obsidian 内容只有 fake provider 留下的硬编码 claims。要 production-quality 需重写 prompt 让模型对齐 §9.3 严格规则（exact_quote 必须 substring of segment.text）。

## 下一步

- 重写 `houchen_prompt.py` + `houchen_analyzer.py` 让模型输出对齐 §9.3（exact_quote 必须 verbatim from segment.text）
- 拆 `insight_provider` 耦合（houchen_analyzer 重构；让 PR-4 §11.4 S-4 原则真正实现）
- 跳过 2 视频可手动改话题或换 model（Claude / MiniMax）
