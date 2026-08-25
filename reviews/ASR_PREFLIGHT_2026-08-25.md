# ASR 预研报告 (Preflight)

> **日期**：2026-08-25
> **触发**：§26 Bundle 阶段 B（仅预研，无实现）
> **禁止项**：未下载模型/媒体、未安装 GPU 依赖

---

## 1. 字幕缺口统计

| 指标 | 值 |
|------|-----|
| 总视频数 | 129 |
| 已有字幕 (frozen) | 50 |
| 无字幕 (missing) | 79 |
| **缺口占比** | **61.2%** |

### 按 collection 分布

| Collection | 总数 | 有字幕 | 无字幕 | 覆盖率 |
|-----------|------|--------|--------|--------|
| videos | 50 | 50 | 0 | **100%** |
| streams | 50 | 0 | 50 | **0%** |
| shorts | 29 | 0 | 29 | **0%** |

### 结论

常规视频字幕已 100% 覆盖。缺口**全部集中在 streams (50) 和 shorts (29)**。

---

## 2. Missing 视频抽样评估 (10 条)

### Streams 样本 (前 5，按直播编号倒序)

| video_id | title (截断) | 值得 ASR? |
|----------|-------------|-----------|
| `Z1HWDoSaC5Q` | [LIVE 104] 代表性问题 + Q&A | ✅ 深度内容 |
| `-9qyfgyKkaU` | [LIVE 103] 化债之夜 + Q&A | ✅ 深度内容 |
| `ScbTzleF3Pc` | [LIVE 102] 化债之夜 | ✅ 深度内容 |
| `epg0aoUbPN4` | [LIVE 101] AI市民茶室 Fable | ✅ 深度内容 |
| `E9uJV2bwzjM` | [LIVE 100] ASK ME ANYTHING 化债 | ✅ 深度内容 |

### Shorts 样本 (前 5)

| video_id | title (截断) | 值得 ASR? |
|----------|-------------|-----------|
| `MxJASieBYok` | AI替代所有工作？ | ⚠️ 短内容 |
| `PqC5J8dtsto` | ChatGPT三大秘诀 | ⚠️ 短内容 |
| `uSuOrC1c-C0` | AI替代工作顺序 | ⚠️ 短内容 |
| `QBOa9crCz1E` | AI学会叹气 | ⚠️ 短内容 |
| `N46JEmhqVCI` | 川普贸易战大转弯 | ⚠️ 短内容 |

### 评估

- **Streams**: 高价值。深度时政/经济分析，通常 1-3 小时，产出 claims/concepts 潜力大
- **Shorts**: 低价值。≤60s 碎片内容，claim 密度低，ASR 成本高（下载 + 转写）

---

## 3. 候选技术

### faster-whisper (推荐)

| 属性 | 说明 |
|------|------|
| 引擎 | CTranslate2 加速的 Whisper |
| 模型 | tiny(39M) / base(74M) / small(244M) / medium(769M) / large-v3(1.5G) |
| 中文质量 | medium+ 可用，large-v3 接近商用水平 |
| CPU 可行 | small 模型在 Apple Silicon 约 2-4x realtime |
| 磁盘 | small≈500MB, medium≈1.5GB (模型+缓存) |
| 依赖 | `pip install faster-whisper` (~50MB), 无 GPU 必需 |

### 预估处理时间 (CPU, Apple Silicon)

| 范围 | 视频数 | 预估时长 (音频小时) | 转写时间 (small, 4x RT) |
|------|--------|---------------------|------------------------|
| 试点 | 3 | ~6h | ~1.5h |
| Streams 全量 | 50 | ~75-125h (估) | ~19-31h |
| Shorts 全量 | 29 | ~0.5h | ~8min |

> ⚠️ duration_sec 字段为 0，音频时长需从 YouTube 元数据或下载后获取

### 媒体保留决策

| 方案 | 磁盘 | 建议 |
|------|------|------|
| 仅提取音频 (opus/mp3) | ~30MB/h | ✅ 推荐 |
| 保留视频 | ~200MB/h | ❌ 浪费 |
| 转写后删音频 | 0 | ⚠️ 不可复验 |

建议：**保留音频文件**作为转录质量审计依据，预计 50 streams ≈ 1.5-3.75 GB。

---

## 4. 试点方案草案

### 规模

3 个 streams（从编号最高/LIVE 104, 103, 102 开始）

### 验收标准

1. **词错误率 (WER)**: 人工抽检 2 分钟片段，WER < 15%（中文）
2. **时间戳精度**: 段级对齐误差 < 2s
3. **Claim 可提取**: 试点 3 视频至少产出 5 条可入库 claim
4. **处理时间**: 单视频转写 < 30min（1-2h 音频，CPU）
5. **存储**: 音频 + transcript JSON 总磁盘 < 500MB/视频

### 试点步骤

1. `yt-dlp --extract-audio --audio-format mp3` 提取 3 个 stream 音频
2. `faster-whisper` small 模型转写 → JSON segments
3. 对接现有 `normalize` pipeline（VTT/JSON3 格式适配）
4. 跑 `analyze` + `validate` 验证 claim 提取质量
5. 人工抽检 WER

---

## 5. 建议

### **`GO_PILOT`**（有条件）

**理由**：
1. 50 个 streams 是高价值深度内容，当前 0% 字幕覆盖是明显的 corpus 缺口
2. faster-whisper small 模型 CPU 可行、无需 GPU 投资
3. 试点 3 视频成本低（~2h 处理 + 1h 人工审核），可验证 ROI
4. streams 内容（时政/经济分析）的 claim 密度高，对 corpus 质量贡献大

**条件**：
1. 试点 WER < 15% 后再扩量
2. shorts 暂不 ASR（claim 密度太低）
3. 音频保留策略确认后再批磁盘预算

**风险**：
- LIVE stream 音频质量可能差（背景噪音/多人对话）→ WER 可能偏高
- duration_sec=0 无法精确预估成本 → 试点阶段校准
