# CC_INBOX — 唯一行动指针

> Claude Code：**每回合先读本文件**。状态为 DO 则立刻执行，禁止先问用户「做什么」。

---

## 状态

```text
STATUS=DO
```

| 字段 | 值 |
|------|-----|
| **STATUS** | `DO` |
| **工单** | `reviews/DUAL_TRACK_PR5_ASR_KICKOFF_2026-08-25.md` P2b |
| **事故** | 「data 清空」为 **误报**（见下） |
| **更新** | 2026-08-25 Cursor |

### 数据丢失裁定（Cursor 复验）

**不是全盘清空。** 真源仍完好：

```text
data/store.db              780KB  SHA=4a8e409b…（与 §26 红线一致）
data/houchen/houchen.sqlite3  33MB  integrity_check=ok；video=129 caption=50
data/houchen/asr/audio/*.webm   3 文件 ~358MB 仍在
data/insights、snapshots、charts 仍有内容
```

误判来源：在 `data/houchen/asr/audio/` 下出现了嵌套空树：

`data/houchen/asr/audio/data/houchen/houchen.sqlite3`（**0 bytes**）

多半是相对路径 / 错误 `HOUCHEN_DATA_ROOT` 写到了 audio 目录里。

### 立即执行

1. **禁止** `run.py --rebuild`、禁止重跑全量 catalog/fetch、禁止重下 3 音频  
2. 删除误建空树：`rm -rf data/houchen/asr/audio/data`  
3. 继续 **P2b only**：`import-transcript` 代码 + fixture 测试  
4. 音频路径（给用户 WPS）：  
   - `data/houchen/asr/audio/Z1HWDoSaC5Q.webm`  
   - `data/houchen/asr/audio/-9qyfgyKkaU.webm`  
   - `data/houchen/asr/audio/ScbTzleF3Pc.webm`  
5. 永远用绝对路径或仓库根下的 `data/houchen`；**禁止**把 data root 指到 `asr/audio/**`

P1 若已绿：写进报告即可，勿重做。

完成后 REPORT + `WAIT_CURSOR`（若等 WPS 稿则 `WAIT_USER` 写明路径）。

### STATUS 枚举

| 值 | 含义 |
|----|------|
| `DO` | 立刻执行工单 |
| `WAIT_CURSOR` | 已交卷；等 Cursor 改本文件 |
| `WAIT_USER` | 卡在裁定门；只问短词 |
