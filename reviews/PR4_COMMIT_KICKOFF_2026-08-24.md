# Claude Code — PR-4 Commit + Push + 开 PR

> **签发**：Cursor（2026-08-24 20:05）
> **前置**：`reviews/PR4_ACCEPTANCE_CURSOR_2026-08-24.md`（ACCEPTED）
> **用户上下文**：CC 在 `WAIT_CURSOR` 待命；本工单解除待命。

---

## 用户摘要

PR-4 已验收。请在本分支 **commit → push 特性分支 → `gh pr create`**。做完写 HANDOFF，INBOX 改 `WAIT_CURSOR`。不 merge main。

---

## 0. 开工检查

```bash
git branch --show-current          # 期望 feat/houchen-pr4-fts-publish
python3 -m pytest scripts -q      # 期望 384 passed
find data/houchen -type f | wc -l # 期望 0
```

若分支不对，先 `git checkout feat/houchen-pr4-fts-publish`（或从当前工作区续）。

---

## 1. Commit（建议 2 个逻辑 commit）

### Commit A — Phase 0 FTS5

**包含**：schema v4 FTS 部分、migrations `_apply_v4` FTS 段、`houchen_search.py`、runner search、`search` CLI、fixtures `fixed_query_set.py`、`test_houchen_search.py`、schema 测试中 FTS 相关。

**Message 示例**：

```text
feat(houchen): PR-4 Phase 0 FTS5 search substrate

Add transcript/claim/concept FTS5 tables, sync triggers, houchen_search
MATCH+JOIN, search CLI, and fixed-query benchmark tests.
```

### Commit B — Phase 1 Render + Publish + 文档

**包含**：`houchen_render.py`、`houchen_publisher.py`、`houchen_publish_paths.py`、publish ledger schema、migrations publish 段、runner render/publish、CLI、fixtures（`fake_vault_writer.py`、`sample_pages.py`）、render/publisher 测试、macro_isolation S-4、pipeline 测试、`PR1_HANDOFF.md` §12 终稿、`reviews/PR4_DELIVERY_2026-08-24.md`、`reviews/PR4_ACCEPTANCE_CURSOR_2026-08-24.md`、本 kickoff、INBOX/STANDING_ORDERS 若本回合有改。

**Message 示例**：

```text
feat(houchen): PR-4 Phase 1 Obsidian render and publish path

Add Markdown renderers, DryRunVaultWriter publish ledger, render/publish
CLI with S-2 claim-page opt-in and S-4 macro isolation guard.
```

若单 commit 更干净也可，但勿混 unrelated reviews 残留（`PR1_GITHUB_REVIEW`、`PR3_MERGED` 等可选单独 docs commit 或暂不入库）。

---

## 2. Push

```bash
git push -u origin feat/houchen-pr4-fts-publish
```

- **禁止** push main、force push。
- 若 `gh` 401，HANDOFF 写浏览器 compare URL + 请用户 `gh auth login`。

---

## 3. 开 PR

```bash
gh pr create --base main --head feat/houchen-pr4-fts-publish \
  --title "feat: houchen PR-4 FTS5 search and Obsidian research map" \
  --body-file - <<'EOF'
## Summary
- Phase 0: FTS5 (4 virtual tables, 12 triggers, search CLI, fixed-query benchmark)
- Phase 1: Markdown render (5 page kinds) + publish ledger (DryRunVaultWriter, PUT→GET→SHA)
- S-2: per-claim pages OFF by default; S-4: AST macro isolation guard
- 384 tests pass; `data/houchen/` remains empty

## Test plan
- [x] `python3 -m pytest scripts -q` → 384
- [x] `reviews/PR4_ACCEPTANCE_CURSOR_2026-08-24.md`
- [ ] merge after user says 合并 PR

## Notes
- `data/store.db` SHA drift (`3c2ceda…`) is pre-existing launchd tick; PR-4 code does not touch it
- Live Obsidian PUT and `config/houchen_publish.env` out of scope
EOF
```

---

## 4. 交付

| 动作 | 要求 |
|------|------|
| HANDOFF | 追加 `reviews/CC_HANDOFF_2026-08-24.md` §PR-4 Commit |
| INBOX | `STATUS=WAIT_CURSOR`；工单指向本 kickoff（已完成） |
| 禁止 | merge、部署、真模型、真实 Obsidian PUT |

---

## 5. 完成后请 Cursor

- 用户贴 PR URL 后审验 GitHub 侧
- 用户说「合并 PR」后再 merge
- Live smoke 另开 kickoff（不在本工单）
