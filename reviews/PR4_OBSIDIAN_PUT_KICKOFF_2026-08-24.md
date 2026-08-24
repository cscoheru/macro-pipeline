# Claude Code — Obsidian PUT（live publish）

> **签发**：Cursor（2026-08-24）  
> **触发**：用户「Obsidian PUT」  
> **前置**：`ObsidianLocalRestWriter` 已实现（`lib/houchen_publisher.py`）；CLI `--apply` 已接线

---

## 用户摘要

把 live smoke 已渲染的 3 个视频页 **PUT 进 Obsidian**（`Research/世界苦茶/video/*.md`）。做完写 HANDOFF + 可选 `PR4_OBSIDIAN_PUT_REPORT_*`。

---

## 0. 实现状态（Cursor 已做）

- `ObsidianLocalRestWriter` + `obsidian_writer_from_env()`
- `load_publish_config()` → `config/houchen_publish.env`
- `publish --apply --operator-authorized` 使用真实 writer（非 DryRun）
- `config/houchen_publish.env.example`

**你若在旧分支**：`git pull origin main` 或合并上述改动后再执行 §1。

---

## 1. 创建 `config/houchen_publish.env`

Obsidian 须已打开且 Local REST API 插件启用。

```bash
cd /Users/kjonekong/macro-pipeline
cp config/houchen_publish.env.example config/houchen_publish.env
chmod 600 config/houchen_publish.env
```

从现有宏观 `config/rest.env` 复制 token（**勿 commit**）：

```bash
# 手工编辑，或：
PORT=$(grep '^OBSIDIAN_PORT=' config/rest.env | cut -d= -f2)
TOKEN=$(grep '^OBSIDIAN_TOKEN=' config/rest.env | cut -d= -f2)
sed -i '' "s|<paste apiKey here>|${TOKEN}|" config/houchen_publish.env
sed -i '' "s|27124|${PORT}|" config/houchen_publish.env
```

---

## 2. 发布 3 个已渲染视频页

```bash
cd /Users/kjonekong/macro-pipeline

python3 scripts/houchen_pipeline.py publish \
  --kind video \
  --apply \
  --operator-authorized \
  --actor live-obsidian-put
```

期望：`published_count=3`，`status=success`，Obsidian vault 出现：

```text
Research/世界苦茶/video/cYP5Hc-ypOM.md
Research/世界苦茶/video/yVESr3OO7Gg.md
Research/世界苦茶/video/uQmOzzgCzQg.md
```

---

## 3. 验证

```bash
sqlite3 data/houchen/houchen.sqlite3 \
  "SELECT vault_path, status FROM publish_record;"
shasum -a 256 data/store.db   # 应仍为 3c2ceda…
python3 -m pytest scripts/test_houchen_publisher.py -q
```

在 Obsidian 中打开上述路径确认页面可读。

---

## 4. 红线

- 禁止写 `data/store.db`
- 禁止 import `lib/vault_writer` / `insight_publisher`
- env 文件 chmod 600，不 commit

---

## 5. 交付

| 动作 | 要求 |
|------|------|
| HANDOFF | publish summary JSON、3 vault_path、store.db SHA |
| INBOX | `WAIT_CURSOR` |
| 报告 | 可选 `reviews/PR4_OBSIDIAN_PUT_REPORT_*.md` |

---

## 6. 失败排查

| 现象 | 处理 |
|------|------|
| connection refused | Obsidian 未开 / 端口错 |
| 401 | token 错 |
| readback_mismatch | REST 返回编码与 UTF-8 不一致 → 记入 HANDOFF |
