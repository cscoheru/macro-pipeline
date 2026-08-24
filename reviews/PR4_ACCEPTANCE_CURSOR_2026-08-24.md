# PR-4 Cursor 独立验收报告

> **签发**：Cursor 架构/质量审核（只读，2026-08-24 20:05）
> **对照**：`reviews/PR4_PLAN_AUDIT_2026-08-24.md` ↔ `reviews/PR4_DELIVERY_2026-08-24.md`
> **CC 入口**：`reviews/PR4_COMMIT_KICKOFF_2026-08-24.md`（INBOX 已指向）

---

## 用户摘要

| 项 | 结果 |
|----|------|
| **PR-4 功能** | **PASS**（Phase 0 FTS5 + Phase 1 render/publish） |
| **PR-1 红线（houchen）** | **PASS**（`data/houchen/` 0 文件；S-4 隔离守卫绿） |
| **`data/store.db`** | **⚠️ 再次漂移**（`3c2ceda…`，非 PR-4 引入；见 §4） |
| **Commit / Push** | **未做**（等 COMMIT kickoff） |
| **Live Obsidian PUT** | 未执行（符合 scope） |

**裁定：PR-4 ACCEPTED（本地实现）。** 下一步：commit → push 特性分支 → 开 PR。

---

## 1. 独立复验（2026-08-24 20:05）

```text
scripts 全量                                → 384 passed
PR-4 专项 (search+render+publisher)         → 61 passed
S-4 AST 守卫                                → 1 passed
py_compile lib/houchen_*.py + pipeline      → exit 0
data/houchen/ 文件数                        → 0 ✅
data/store.db SHA                           → 3c2ceda61c24… ⚠️（见 §4）
分支                                        → feat/houchen-pr4-fts-publish（未 commit）
```

---

## 2. 计划审核项闭环

| ID | 要求 | 核验 |
|----|------|------|
| F-1 | `transcript_fts` 不用 `new.video_id` | ✅ 触发器写 `transcript_version_id`；`houchen_search` JOIN 溯源 |
| F-2 | store.db 基线写 SHA 非 git SHA | ✅ 计划 §Verification 已修正 |
| S-2 | v1 默认不生成 per-claim 页 | ✅ runner/CLI/render 三处拒绝；`claim` 保留在 CHECK |
| S-4 | 禁止 `insight_publisher` / `store.db` 耦合 | ✅ AST 守卫 + 手工 grep 双确认 |

---

## 3. 交付清单勾选

### Phase 0 — FTS5

- [x] 4 张 FTS5 虚表 + 12 触发器（trigram tokenizer；plain DELETE 替代 contentless delete）
- [x] `houchen_search.py` MATCH + JOIN 溯源
- [x] `search` CLI（只读）
- [x] `fixed_query_set.py` 固定查询基准
- [x] `test_houchen_search.py` 23 cases

### Phase 1 — Render + Publish

- [x] 5 类页（video / concept / forecast / review_queue / coverage）
- [x] `houchen_render.py` 确定性 SHA
- [x] `houchen_publisher.py` PUT→GET→SHA + `DryRunVaultWriter`
- [x] `houchen_publish_paths.py` 路径隔离
- [x] `render` / `publish` CLI；双门禁 `--apply --operator-authorized`
- [x] `houchen_status` 增 `publish_state` / `search_index_size`
- [x] schema v4 三表 + CHECK 扩宽

### 隔离

- [x] 新模块无 `import insight_publisher`
- [x] 新模块可执行代码无 `data/store.db` 字面量
- [x] `data/houchen/` 0 文件

### 未作（声明一致）

- [ ] `ObsidianLocalRestWriter`（live publish 另开）
- [ ] `config/houchen_publish.env` 创建
- [ ] commit / push / merge

---

## 4. `data/store.db` 漂移（非阻断 PR-4）

| 基线 | SHA |
|------|-----|
| PR-1 接受基线（§9.5） | `52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7` |
| 当前实测 | `3c2ceda61c24e3736864ab3ad0cf6d4ab751a67ac20fb848ba769db0291d9d32` |

- S-4 AST 守卫确认 PR-4 代码未引用 `data/store.db`。
- 与 PR-1 R3 同类根因：launchd 宏观 pipeline 定时跑改写 `store.db`。
- `lib/presnapshot.py` 已就位；建议后续工单跟踪「接受新基线」或「launchd 与 houchen 窗口隔离」。
- **不阻断 PR-4 功能验收与 commit**；merge 前由用户裁定是否再次 re-baseline。

---

## 5. Verdict

**PR-4 ACCEPTED（Cursor 2026-08-24）。**

- 384 tests pass；F-1/F-2/S-2/S-4 全部闭环。
- 下一步工单：`reviews/PR4_COMMIT_KICKOFF_2026-08-24.md`。
- Live smoke（catalog → publish 垂直切片）在用户授权后另开 `LIVE_SMOKE` kickoff，不在本回合。
