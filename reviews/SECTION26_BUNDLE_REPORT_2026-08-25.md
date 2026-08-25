# §26 Bundle Report (2026-08-25)

> **执行者**: Claude Code (CC)
> **工单**: `reviews/SECTION26_BUNDLE_KICKOFF_2026-08-25.md`
> **状态**: DONE → WAIT_CURSOR

---

## store.db SHA

```
before = 4a8e409b7279b72a57364ef735f5f6066a20b6d99352d676dc94d9a549e8a43c
after  = 4a8e409b7279b72a57364ef735f5f6066a20b6d99352d676dc94d9a549e8a43c
✅ MATCH — 宏观库零写入
```

---

## A — 全量字幕抓取

### 汇总

| 指标 | 值 |
|------|-----|
| 总视频 | 129 |
| frozen (有字幕) | 14 → **50** (+36) |
| missing (无字幕) | 79 |
| pending | 115 → **0** |
| normalized | 14 → **50** (+36) |
| permanent_error | 0 |
| retryable | 0 |
| auth_required | 0 |

### 批次执行记录

| 批次 | scope | frozen | missing |
|------|-------|--------|---------|
| 1 | 20 | 20 | 0 |
| 2 | 30 | 16 | 14 |
| 3 | 30 | 0 | 30 |
| 4 | 30 | 0 | 30 |
| 5 | 5 | 0 | 5 |
| **合计** | **115** | **36** | **79** |

### Missing 分布

| Collection | Missing | 说明 |
|-----------|---------|------|
| streams | 50 | LIVE 直播回放，YouTube 未生成字幕 |
| shorts | 29 | 短视频，通常无字幕 |
| videos | 0 | **100% 覆盖** |

### 已知跳过 ID

- `f_jd_j3eEuE` — 上下文纪律标记的易触发过滤 ID（未在本次 fetch 中出现）

---

## B — ASR 预研

**交付**: `reviews/ASR_PREFLIGHT_2026-08-25.md`

### 核心结论

- 缺口 79 视频 = 50 streams + 29 shorts
- **Streams 高价值**（深度时政/经济分析），Shorts 低价值
- 推荐技术: `faster-whisper` small 模型（CPU 可行，无需 GPU）
- **建议**: `GO_PILOT`（3 streams 试点，验收 WER < 15%）

### 试点成本估算

| 范围 | 预估音频时长 | 转写时间 (4x RT) |
|------|-------------|-----------------|
| 3 streams 试点 | ~6h | ~1.5h |

---

## C — PR-5 计划

**交付**: `docs/plans/pr5-macro-bridge.md`

### 核心设计

- **零写宏观库**: `store.db` 以 `?mode=ro` + `PRAGMA query_only` 只读打开
- **新表 `macro_link_candidate`** 建在 houchen.db（非 store.db）
- **关系类型**: `supports | challenges | contextualizes | unresolved`
- **匹配策略**: 首版 keyword_match（关键词映射可配置）
- **升级路径**: reviewed candidate → external_evidence + evaluation（复用 PR-3 设施）
- **文件数**: 6（≤8 约束满足）
- **退出条件**: store.db SHA 不变 + 55 accepted claims 全扫 + JSONL 导出 + 测试全绿

---

## 红线验证

| 红线 | 状态 |
|------|------|
| store.db SHA before == after | ✅ |
| 不弱化 houchen_validator / houchen_quote | ✅ 未触碰 |
| 不做全频道 analyze | ✅ 未执行 analyze |
| 不 push | ✅ 未 push |
| 日志无 API key | ✅ |
| 不下载模型/媒体 | ✅ |

---

## 交付物清单

| 文件 | 状态 |
|------|------|
| `reviews/HOUCHEN_CAPTION_COVERAGE_2026-08-25.md` | ✅ |
| `reviews/ASR_PREFLIGHT_2026-08-25.md` | ✅ |
| `docs/plans/pr5-macro-bridge.md` | ✅ |
| `reviews/SECTION26_BUNDLE_REPORT_2026-08-25.md` | ✅ (本文件) |
| `reviews/CC_INBOX.md` | ✅ → WAIT_CURSOR |
