# PR-4 Prompt Align Report (v2 — 仍 0 accepted；停等 Cursor)

> **签发**：Claude Code（2026-08-25）
> **响应**：`reviews/PR4_PROMPT_ALIGN_KICKOFF_2026-08-25.md`
> **门禁**：单视频 ≥1 real accepted → render → publish
> **结果**：**0 accepted**；停等 Cursor 调 prompt

---

## 同步

- `main` @ `4bbe009`（已是最新；HEAD = PR-4 main）
- `config/houchen_analysis_prompt.md` v2（Cursor 写入）：每条 claim 严格 single-segment 引用、exact_quote 必须 verbatim ≥4 char、3-8 claims/video
- `lib/houchen_prompt.py` `PROMPT_VERSION = "2026-08-25.1"` + INPUT bundle 含 `raw_caption_sha256`

## 试跑（7DsxtHsOCzA）

```text
analyze --provider deepseek --no-pending --video-id 7DsxtHsOCzA
  → success（deepseek-chat）
validate --video-id 7DsxtHsOCzA
  → partial: validated=0, rejected=8
```

## 拒因占比（最新 run = `hcrun_01a03666e85b71aeb9430ff76d8be730`）

| Rule | 数量 | % | 说明 |
|------|----:|--:|------|
| **R10** | 4 | 50% | model 输出 `layer='speaker_statement'`（brief §3.1.5 禁；只允许 human-curated）|
| **R2**  | 4 | 50% | `exact_quote` 不在 segment.text 中（NFC + whitespace fold 后仍不匹配）|
| **Total** | 8 | 100% | |

历史 reject（R1 = 缺 `raw_caption_sha256`）属旧 attempt（前 run）；新 v2 prompt 的 INPUT bundle 已含此字段，R1 触发的 reject 不会再来。

## 关键发现

- **v2 prompt 让 R1 失效**（原始 schema 缺 raw_caption_sha256 的 R1 报错消失）。
- **R2 仍 50%**：模型生成的 `exact_quote` 仍不是 segment.text 的 verbatim 子串。可能模型仍做「总结式引文」而非精确复制。
- **R10 仍 50%**：模型仍给 `speaker_statement`（仅 human-curated 允许；model 必须 `speaker_reasoning` / `system_evaluation`）。prompt v2 没强制约束 layer。
- **0 real accepted**：3 个 accepted claim 仍是 fake provider 留下的硬编码；Obsidian 内容未变。

## 红线

```text
data/store.db 前 = 后 = 3c2ceda61c24…  (0 漂移)
data/houchen 16 → 49 文件（路线 2 retry render+publish 增量；本次 0 写入）
```

S-4 AST 隔离守卫：通过。

## 停等 Cursor 调 prompt

- v3 prompt 候选修正方向（Cursor 决策）：
  - **R10 修法**：prompt 显式禁止 `speaker_statement`（只许 `speaker_reasoning` / `system_evaluation`）
  - **R2 修法**：
    - 选项 A：prompt 加 exact_quote → segment.text 双重验证指令（先输出 quote，模型自查 substring）
    - 选项 B：few-shot 例子，每个 claim 配 verbatim 引文
    - 选项 C：分两步 — 先列 candidate segment ordinals，再只对 selected segments 写 claim

## 测试

```text
python3 -m pytest scripts -q   → 386 passed (无回归)
```

## 下一步

等 Cursor 出 v3 prompt + 新 kickoff 重试单视频。
