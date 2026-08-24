# 运维核验：`data/store.db` 预快照（presnapshot）

日期：2026-08-24  
关联：PR-1 R3 红线 re-baseline、`lib/presnapshot.py`、`PR1_HANDOFF.md` §9.6  
结论：**机制已落地且测试通过；待首次 launchd  tick 实证 + 文档/工具补齐**

---

## 1. 核验摘要

| 项 | 结果 | 证据 |
|----|------|------|
| `lib/presnapshot.py` 存在 | ✅ | gzip + SHA 校验 + 原子写入 + keep=30 轮转 |
| `run.py` 在 `main()` 首行调用 | ✅ | L861 `presnapshot.snapshot_store_db`，早于 `setup_logging()` L879（AST 测试证实） |
| 单元/接线测试 | ✅ | `scripts/test_presnapshot.py` **11 passed** |
| 全 `scripts` 回归 | ✅ | **203 passed**（较 PR-1 验收 +11） |
| 手工 smoke 快照 | ✅ | `data/backups/store-20260824-115556.db.gz`（11:55） |
| 快照与 live `store.db` SHA 一致 | ✅ | 均为 `52c12c82…` |
| launchd 定时任务已装 | ✅ | plist Hour=9/16 Minute=7 |
| launchd 下 presnapshot 日志 | ⏳ | **尚无** `[presnapshot]` 行（机制 11:55 后才接入） |
| R2 基线 `38328cd0…` 可本地恢复 | ❌ | 无 git、无 presnapshot 历史、legacy `.bak` 亦为其他 SHA |

---

## 2. 当前磁盘状态

```text
data/store.db
  SHA-256: 52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7
  mtime:   2026-08-24 09:07:28

data/backups/store-20260824-115556.db.gz   # 手工 smoke，非 09:07 前快照
  plain SHA: 52c12c82…（与当前 store 相同）
  size: 161,502 bytes

legacy（非 presnapshot 体系）:
  data/store.db.bak.20260813-101734 → 168865ce…
  backups/store.db.bak.20260814-210255 → 5a07e1bc…
```

**含义**：今日 09:07 launchd 改写发生在 presnapshot 接入**之前**；当前唯一 presnapshot 是改写**之后**的状态。R2 基线在任何本地副本中均已不可恢复——与 handoff §9.4 一致。

---

## 3. 机制设计核验（符合运维目标）

- **时机**：每次 `run.py` 入口（含 launchd 09:07 / 16:07）在写库**之前**快照。
- **路径**：`data/backups/store-YYYYMMDD-HHMMSS.db.gz`（`data/` gitignored，不污染仓库）。
- **安全**：目录 `0700`、文件 `0600`；失败 swallow，不阻断 pipeline。
- **可观测**：成功时 stdout 一行 `[presnapshot] wrote … sha=… kept=N` → `logs/launchd.out.log`。
- **保留**：默认 30 份按 mtime 删最旧。

---

## 4. 下一步执行建议（按优先级）

### A. 今日必做 — launchd 首次实证（~16:07 后）

无需改代码。16:07 tick 完成后执行：

```bash
# 1) presnapshot 是否写入 launchd 日志
grep presnapshot logs/launchd.out.log | tail -5

# 2) 是否新增 gzip 快照（应 ≥2 个文件：11:55 smoke + 16:07 tick）
ls -lt data/backups/

# 3) 16:07 快照的 plain SHA（应为 tick 开始前状态）
python3 -c "
import gzip, hashlib, glob, os
files = sorted(glob.glob('data/backups/store-*.db.gz'))
for p in files[-2:]:
    with gzip.open(p,'rb') as f:
        h = hashlib.sha256(f.read()).hexdigest()
    print(os.path.basename(p), h[:16]+'…', os.path.getsize(p))
"
```

**通过标准**：`launchd.out.log` 出现 `[presnapshot] wrote`；`data/backups/` 有 `store-20260824-1607xx.db.gz`（时间戳近似 16:07:00）。

### B. 短期 — 验收/审计工作流（建议实现，小改动）

1. **`scripts/verify_store_redline.py`**（或 shell 包装）  
   - 列出 `data/backups/` 各快照 plain SHA + mtime  
   - 对比当前 `data/store.db` SHA  
   - 可选：`--expect <sha>` 用于验收红线一键检查  
2. **`scripts/restore_store_from_snapshot.py`**  
   - 从指定 `.db.gz` 恢复到 `data/store.db`（需显式 `--force` + 二次确认）  
3. **README.md** 增补一节：`data/backups/`、presnapshot、红线验收命令示例  

预估：1 个 PR，~150 行 + 测试，不改变 pipeline 行为。

### C. 中期 — 异地容灾（运维习惯，非代码）

`data/` 与 `data/backups/` 均在 `.gitignore`：

- Time Machine 已覆盖则确认 `data/backups` 在备份范围内  
- 或每周 `rsync -a data/backups/` 到 NAS / 另一磁盘  
- 验收周期长时：在 handoff 中记录「比对 SHA 用 presnapshot 列表」而非仅 live 文件

### D. 不建议

- 把 `data/store.db` 纳入 git（体积 + 二进制冲突）  
- 在 launchd plist 里单独跑快照（已与 `run.py` 合并，重复易竞态）  
- 为恢复 R2 `38328cd0…` 再花时间（本地无副本；新基线 `52c12c82…` 已接受）

---

## 5. 与 PR-1 / PR-2 边界

- presnapshot 属**宏观 pipeline 运维**，不修改 houchen 代码或 PR-1 红线五文件。  
- PR-2 启动**不依赖**本运维项完成；但建议在 PR-2 长周期开发前完成 **A + B**，避免再次 re-baseline 争议。

---

## 6. 等待用户确认后的执行项

| 序号 | 动作 | 谁执行 | 阻断？ |
|------|------|--------|--------|
| 1 | 16:07 后跑 §4.A 核验命令 | 你或 Agent | 否 |
| 2 | 实现 `verify_store_redline` + README | Agent（需你点头） | 否 |
| 3 | 实现 `restore_store_from_snapshot` | Agent（需你点头） | 否 |
| 4 | 配置 Time Machine / rsync | 你 | 否 |
| 5 | 启动 PR-2 | Agent | 独立于运维 |

**推荐顺序**：1 →（可选 2+3）→ 4 并行 → 5。
