# Claude Code — 审验结论与执行工单

> **受众**：Claude Code（实现 Agent）  
> **签发**：Cursor 架构/质量审核（只读，2026-08-24）  
> **滚动状态**：见 **`reviews/CC_STATUS_2026-08-24.md`**（优先读）  
> **用户**：仅需在 `CC_STATUS` §5 裁定；勿在对话中重复审验细节。

---

## 0. 当前状态一句话（2026-08-24 13:05 更新）

- **PR-1 / PR-2**：ACCEPTED；P2-A/B、Live smoke、OPS-2 **均 DONE**
- **测试**：259/259（含 verify_restore 15）；红线 `52c12c82…` 0 漂移
- **GIT-1**：**可立即 commit**（用户已授权；清单见 `CC_STATUS` §3）
- **勿 push**；PR-3 实现仍禁止直至 P2-C 计划批准

---

## 1. 你先读什么（顺序）

| 优先级 | 文件 |
|--------|------|
| 1 | 本文件 |
| 2 | `reviews/PR2_DELIVERY_2026-08-24.md` |
| 3 | `docs/厚辰/世界苦茶研究库/PR1_HANDOFF.md` §10 |
| 4 | `lib/houchen_normalizer.py`、`lib/houchen_quote.py` |
| 5 | `reviews/OPS_presnapshot_verification_2026-08-24.md`（运维，与 PR-2 并行） |

---

## 2. 独立复验结果（Cursor 2026-08-24，可重跑 §8 命令）

```text
python3 -m pytest scripts -q
→ 243 passed

python3 -m pytest scripts/test_houchen_*.py scripts/test_ledger.py scripts/test_migrations.py -q
→ 140 passed（非 handoff 旧写的 100；因 PR-2 新增测试，不是 PR-1 回退）

shasum -a 256 data/store.db
→ 52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7 ✅

5 份 PR-1 基线文件 SHA → 与 handoff §8 完全一致 ✅

find data/houchen -type f | wc -l → 0 ✅

grep store.db lib/houchen_* scripts/houchen_*
→ 仅 houchen_paths.py protected 列表，无读写路径 ✅
```

**裁定**：PR-1 红线 **0 漂移**；PR-2 交付文档中的测试数字需按 §4 工单修正。

---

## 3. PR-2 架构审核结论

### 3.1 PASS 项（无需重做）

- 分层：`houchen_quote`（§8.6 唯一权威）→ `houchen_normalizer` → `run_normalize`
- Merge：`0 < gap ≤ 1500`；gap=0 不合并（与 brief §8.3 及测试一致）
- 幂等：DB UNIQUE + 内容寻址 JSON；文件 SHA 一致不重写
- `speaker=None`；失败 best-effort + `EXIT_PARTIAL=3`；未编目 ID 前置拒绝
- Schema v2 + migration recreate 扩 CHECK；PR-1 相关测试仍绿
- normalize dry-run 只读；无网络；不触宏观 `store.db`

### 3.2 P2 技术债（非阻断，建议工单 P2-A 处理）

| ID | 问题 | 建议 |
|----|------|------|
| P2-1 | `MAX_REPEAT_WINDOW` 常量未使用；`_collapse_repeats` 实际折叠**全部**连续重复，与 docstring「window 上限」不一致 | 删常量+改文档 **或** 实现 window + 测试（与 brief §8.2 对齐后二选一） |
| P2-2 | `transcribe_video` docstring 写「Never raises」但实际 `raise ValueError` | 改 docstring |
| P2-3 | macro E2E 未含 `normalize` 子命令 | PR-3 前扩 E2E 或新增独立 macro 不变测试 |
| P2-4 | 实现文件 `lib/houchen_*.py` 现 9 个 + pipeline；brief §707 >8 需说明 | handoff §10.2 已列职责；验收记录中引用 brief 豁免即可 |
| P2-5 | `PR2_DELIVERY` §6.2 写 40 测试、§1 写 36；PR-1 回归写 100 实际 140 | 统一数字 |
| P2-6 | `normalize_failed` retryable 恒 0 | 记入 PR-3/运维 backlog |

---

## 4. 执行工单（按优先级）

### 等待用户：「接受 PR-2」

以下 **P2-B / P2-C** 可在用户确认前做 **P2-A 文档小修**；**禁止 PR-3 实现代码** 直到用户接受 + P2-C 计划批准。

---

### 工单 P2-A — 小修（可选，≤30min，用户未反对即可做）

1. **P2-1**：`MAX_REPEAT_WINDOW` — 删死常量并改 `_collapse_repeats` docstring **或** 实现 window 逻辑 + 单测（须与 brief §8.2 一致，勿静默改语义）。
2. **P2-2**：`houchen_normalizer.transcribe_video` docstring 改为如实描述 `ValueError`。
3. **P2-5**：更新 `reviews/PR2_DELIVERY_2026-08-24.md`：测试数 36；PR-1 回归 **140**（注明新增 PR-2 测试）。

验证：

```bash
python3 -m pytest scripts/test_houchen_normalizer.py scripts -q
```

---

### 工单 P2-B — 验收记录（用户「接受 PR-2」后立即做）

1. 在 `reviews/PR2_DELIVERY_2026-08-24.md` 追加 **§11 审核裁定**（见本文件 §6 模板，复制粘贴）。
2. 更新 `PR1_HANDOFF.md` §10.8：`PR-2 ACCEPTED (Cursor audit 2026-08-24)`。
3. **不要**改三份 Codex 基线文档、两份 DOCX。

---

### 工单 P2-C — PR-3 Plan-First（推荐与用户接受并行）

**禁止写 PR-3 实现**，仅产出计划文件：

- 路径：`docs/plans/pr3-claim-extraction.md`
- 须含：schema v3 草案、`claim`/`claim_source`、与 `houchen_quote.exact_quote_in_segment` 硬门禁、测试矩阵、拟改文件清单
- 若 >8 实现文件：按 brief §707 写拆分理由
- 交用户 + Cursor 批准后再编码

---

### 工单 OPS-1 — presnapshot 实证（非阻断，今日 16:07 后）

见 `reviews/OPS_presnapshot_verification_2026-08-24.md` §4.A：

```bash
grep presnapshot logs/launchd.out.log | tail -10
ls -lt data/backups/
```

结果写入 `reviews/` 新文件 `OPS_presnapshot_tick_2026-08-24.md`（仅事实，无代码改动）。

---

### 工单 OPS-2 — 验收工具（需用户点头「做 B」）

实现 `scripts/verify_store_redline.py` + 可选 `restore_store_from_snapshot.py` + README 一节。  
**禁止**动 `houchen_*`、宏观 parser、基线文档。

---

### 工单 GIT-1 — 提交（仅用户显式要求 commit）

范围：houchen PR-1+PR-2 + presnapshot + reviews + 测试；**不含** `data/`、`logs/`、`config/*.env`。

```text
feat: houchen PR-1 corpus foundation and PR-2 transcript normalizer
```

**不要 push**，除非用户另行要求。

---

### 工单 SMOKE-1 — Live smoke（仅用户显式授权联网）

独立 `HOUCHEN_DATA_ROOT` temp；subtitle-only；结束后证明无媒体文件。证据写 `reviews/`。

---

## 5. 硬边界（违反即 FAIL）

- 不实现 PR-4/PR-5（FTS、Obsidian 发布）直到对应 PR 验收
- 不修改 `CLAUDE_CODE_IMPLEMENTATION_BRIEF.md` / `CODEX_ACCEPTANCE_PROTOCOL.md` / `ENGINEERING_TEST_PLAN.md`
- 不读写 `data/store.db`；研究库仅 `HOUCHEN_DATA_ROOT`
- PR-3 `exact_quote` 必须 `from houchen_quote import normalize_for_compare` / `exact_quote_in_segment`
- 不弱化测试、不删断言关问题
- 不 commit/push 除非用户要求

---

## 6. §11 模板（粘贴到 `PR2_DELIVERY` 末尾）

```markdown
## 11. 审核裁定（Cursor，2026-08-24）

- **PR-2 功能**：PASS（243/243 scripts；normalizer 36 + pipeline normalize 4）
- **PR-1 红线**：0 漂移（store.db `52c12c82…`；5 基线文件 SHA；houchen 0 文件）
- **Live smoke**：未执行（非 gate）
- **P2 技术债**：见 `reviews/CC_AUDIT_AND_INSTRUCTIONS_2026-08-24.md` §3.2（非阻断）
- **下一步**：用户确认接受后 → P2-B 锁定记录 → P2-C PR-3 计划 → 可选 OPS/GIT/SMOKE
```

---

## 7. 用户裁定门（仅此节需用户回复；CC 勿替用户决定）

用户只需回复下列之一（可复制）：

| 回复 | CC 动作 |
|------|---------|
| **接受 PR-2** | 执行 P2-B；启动 P2-C 计划；P2-A 可选 |
| **接受 PR-2 + 小修** | P2-A + P2-B + P2-C |
| **授权 live smoke** | 另执行 SMOKE-1 |
| **做运维 B** | 执行 OPS-2 |
| **commit** | 执行 GIT-1 |
| **进 PR-3 实现** | 须已有 P2-C 计划批准 + 用户明确指令 |

未列出的组合可写「接受 PR-2 + commit」等。

---

## 8. 自动化复验命令包（交付前自检）

```bash
cd /Users/kjonekong/macro-pipeline

python3 -m pytest scripts/test_houchen_normalizer.py -v
python3 -m pytest scripts/test_houchen_*.py scripts/test_ledger.py scripts/test_migrations.py -q
python3 -m pytest scripts -q
python3 -m py_compile lib/houchen_*.py scripts/houchen_pipeline.py

shasum -a 256 data/store.db \
  docs/厚辰/不明白访谈厚辰.docx \
  docs/厚辰/重庆上街-厚辰.docx \
  docs/厚辰/世界苦茶研究库/CLAUDE_CODE_IMPLEMENTATION_BRIEF.md \
  docs/厚辰/世界苦茶研究库/CODEX_ACCEPTANCE_PROTOCOL.md \
  docs/厚辰/世界苦茶研究库/ENGINEERING_TEST_PLAN.md

find data/houchen -type f | wc -l   # expect 0
```
