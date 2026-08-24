# PR-4 合并后审验（Cursor）

> **签发**：Cursor（2026-08-24 20:24）  
> **对象**：`main` 合并 PR #2 之后  
> **用户触发**：「待审验」

---

## 用户摘要

| 项 | 结果 |
|----|------|
| **合并后审验** | **PASS** |
| **PR #2** | MERGED @ `37ef395`（2026-08-24T12:16:24Z） |
| **`main` tip** | `685148c`（含 post-merge docs） |
| **测试** | 384 passed；PR-4 专项 62 passed；S-4 守卫绿 |
| **Live smoke** | 未执行 |
| **可读成果** | 尚无（`data/houchen/` 0 文件） |

**裁定：PR-4 合并后状态 ACCEPTED。** 厚辰 PR-1～PR-4 工程栈在 `main` 上闭环。

---

## 1. 独立复验

```text
git branch                         → main
git log -1                         → 685148c docs(pr4): post-merge records…
python3 -m pytest scripts -q       → 384 passed
PR-4 专项 (search+render+publisher+S-4) → 62 passed
py_compile lib/houchen_*.py        → OK
find data/houchen -type f          → 0
data/store.db SHA                  → 3c2ceda61c24…
gh pr view 2                       → state=MERGED
```

---

## 2. 合并后核对项

| 检查 | 结果 |
|------|------|
| FTS5 4 表 + 12 触发器在 `main` | ✅ `houchen_schema.py` |
| F-1：`transcript_fts` 无 `video_id` 列 | ✅ JOIN 在 `houchen_search.py` |
| S-2：claim 页默认 OFF | ✅ runner/CLI/render 三处 |
| S-4：无 `insight_publisher` / 可执行代码无 `store.db` | ✅ AST 守卫 |
| `search` / `render` / `publish` CLI | ✅ `houchen_pipeline.py --help` |
| `DryRunVaultWriter`（无 live PUT） | ✅ 符合 scope |
| 宏观 `data/store.db` 未被 houchen 路径改写 | ✅ SHA 稳定于审验窗口 |

---

## 3. `data/store.db` 注记

| 基线 | SHA |
|------|-----|
| PR-1 接受基线 | `52c12c82…` |
| 当前 | `3c2ceda…` |

归类为 **launchd 宏观 pipeline 漂移**（与 PR-4 及合并操作无关）。`lib/presnapshot.py` 已就位；re-baseline 为运维裁定，非 PR-4 阻断项。

---

## 4. PR 栈总览（`main`）

| PR | 能力 | 状态 |
|----|------|------|
| PR-1 | 语料底座、隔离、采集 | ✅ merged |
| PR-2 | 字幕规范化、`exact_quote` | ✅ merged |
| PR-3 | 主张抽取、概念种子、硬校验 | ✅ merged |
| PR-4 | FTS5、Markdown 渲染、发布台账 | ✅ merged |

---

## 5. 未作 / 下一步

| 项 | 说明 |
|----|------|
| Live smoke | 用户说 **live smoke** → `PR4_LIVE_SMOKE_KICKOFF` |
| Obsidian PUT | `ObsidianLocalRestWriter` 未实现 |
| 真模型 analyze | 默认 fake；需另授 |
| 全频道 catalog | 不在首版 scope |

---

## 6. Verdict

**PR-4 POST-MERGE ACCEPTED（Cursor 2026-08-24）。**

工程交付完成；**产品可读成果**待 live smoke。
