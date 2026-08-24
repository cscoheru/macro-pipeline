# Claude Code — 启动 PR-4 实现

> **签发**：Cursor（2026-08-24）  
> **用户授权**：启动 PR-4 实现  
> **前置**：`reviews/PR4_PLAN_AUDIT_2026-08-24.md`（有条件批准）

---

## 用户摘要

已授权编码。CC 按本文件执行；完成后写 `CC_HANDOFF`，停等 Cursor 验收。你无需传话。

---

## 0. 开工前（同一回合、仍可无业务代码）

1. 修订 `docs/plans/pr4-obsidian-research-map.md`：
   - **F-1**：`transcript_fts` / 触发器不得使用 `new.video_id`（表无此列）。用 `transcript_version_id` + JOIN，或触发器内子查询取 `video_id`。
   - **F-2**：Verification 中 `data/store.db` 期望 SHA = `52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7`（禁止写 git SHA）。
   - 建议顺带 S-2：v1 **不**默认生成 per-claim 页。
2. 分支：从 `main`（`47e4de3` 或当前 origin/main）建/续  
   `feat/houchen-pr4-fts-publish`（推荐新名；或清空后重用 `feat/houchen-pr4-plan`）。
3. 遵守 `reviews/CC_STANDING_ORDERS.md`。

---

## 1. Phase 0 — FTS5（先绿再进 Phase 1）

顺序：

1. `houchen_schema.py` — `_V4_*` FTS 虚表 + triggers（F-1 修正版）+ CHECK 扩宽  
2. `houchen_migrations.py` — `_apply_v4()`；无 FTS5 → fail-closed  
3. `houchen_search.py` — MATCH + JOIN 溯源  
4. `houchen_runner` / CLI — `search`（只读）  
5. fixtures：`fixed_query_set.py`  
6. 测试：`test_houchen_search.py` + schema v4/fts  

**门禁（全部通过才进 Phase 1）：**

```bash
python3 -m pytest scripts/test_houchen_search.py scripts/test_houchen_schema.py -q
python3 -m pytest scripts/test_houchen_*.py scripts/test_ledger.py scripts/test_migrations.py -q
shasum -a 256 data/store.db   # 52c12c82…
find data/houchen -type f | wc -l   # 0
```

---

## 2. Phase 1 — Render + Publish

1. `houchen_publish_paths.py` + `houchen_render.py` + `houchen_publisher.py`  
2. 禁止 `import insight_publisher`；禁止碰 `data/store.db`（测试 grep 守护）  
3. `render` / `publish` CLI；默认 dry-run；真实 PUT 仅 `--apply --operator-authorized`  
4. FakeVaultWriter；扩展 pipeline / macro_isolation（含 render→publish 链）  
5. 页面：video / concept / forecast / review_queue / coverage（claim 页默认关闭）

**门禁：**

```bash
python3 -m pytest scripts/test_houchen_render.py scripts/test_houchen_publisher.py -q
python3 -m pytest scripts/test_houchen_macro_isolation.py -q
python3 -m pytest scripts -q   # expect ≥510（计划估值；以实际为准写入手册）
python3 -m py_compile lib/houchen_*.py scripts/houchen_pipeline.py
```

---

## 3. 交付与 Git

| 动作 | 规则 |
|------|------|
| Commit | 特性分支；可用 2 commit（phase0 / phase1）或逻辑清晰的少量 commit |
| Push | **仅当**用户曾授「push 特性分支」或本工单结束后 Cursor 另授；默认先本地完成 + HANDOFF |
| docs | `PR1_HANDOFF.md` §12 PR-4；`reviews/PR4_DELIVERY_*.md` |
| HANDOFF | `reviews/CC_HANDOFF_*.md`：测试数、红线、文件清单、未做项 |

**禁止**：push main、force、部署、真模型、真实 Obsidian PUT（除非用户另授 live publish smoke）、改 Codex 基线/DOCX。

---

## 4. Cursor 验收入口（你完成后）

停并请求审验。Cursor 将对照本文件 + plan + delivery 出具 `PR4_ACCEPTANCE_*`。

---

## 5. 修订历史

| 时间 | 事件 |
|------|------|
| 2026-08-24 18:00 | 用户「启动 PR-4 实现」；F-1/F-2 必须先修计划 |
