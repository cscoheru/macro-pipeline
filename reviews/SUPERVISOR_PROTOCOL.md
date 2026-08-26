# Cursor 代值守协议（用户 2026-08-25：两小时回来）

Cursor **自动验收 + 派下一刀**，不叫用户。仅下列情况写 `WAIT_USER`：

| 必须用户裁定 |
|--------------|
| `promote_to_canonical` |
| 云端 ASR / 按量 API 花钱 |
| 全频道 637 catalog |
| ASR 试点 **&lt;2/3** 视频 accepted（质量 DEFER） |
| 新外源、无 video_id、或要改 brief 产品范围 |
| 写 `data/store.db` |

**已授权自动推进：** 忽略 shorts；本地 ASR 试点 → PASS 后 streams `--limit 5` 再扩；概念页随 claim 增量 refresh；外源仅已点名的 `KLJJuMybVsc`。

## 每轮（Autopilot tick）

先跑 `python3 scripts/cc_autopilot_inspect.py`，再按 `reviews/CC_AUTOPILOT.md`。

1. 读 `reviews/CC_INBOX.md` + `reviews/SUPERVISOR_STATE.md` + `git log -5`
2. `STATUS=WAIT_CURSOR` → 验收 → 派下一刀 `DO` → **立刻 `git push origin main`**
3. `STATUS=DO` 且进度在动 → 只更新 STATE，不改工单；**不准第二路 whisper**
4. `STATUS=DO` 且 **≥25min** tmp/git 无进展 → STATE 记 stalled，不重复派同一工单
5. 计划队列清空且无 stalled → INBOX `WAIT_USER` 一句「队列空」

## 当前计划队列（完成后划掉）

1. [x] ASR 试点 3 streams 交卷并验收  
2. [x] ASR 扩 5 streams（转写+import 5/5；analyze 5/5；本地 render/publish）  
3. [x] 概念页增量 refresh（78 render / 89 publish，无 LLM）  
4. [x] ASR 再扩 5 streams（零 DeepSeek；5/5 入库；render DEFER）  
5. [x] ASR 再扩 5c streams（零 DeepSeek；5/5 入库）  
6. [x] ASR 再扩 5d streams（零 DeepSeek；4/5 入库；`kZUwR4ORFH4` 下载 FAIL）  
7. [x] ASR 再扩 5e streams（零 DeepSeek；5/5 入库；含 `kZUwR4ORFH4` 补下）  
8. [x] ASR 再扩 5f streams（零 DeepSeek；5/5 入库）  
9. [x] ASR 再扩 5g streams（零 DeepSeek；5/5 入库）  
10. [ ] ASR 再扩 5h streams（零 DeepSeek；工单 `ASR_EXPAND5H_KICKOFF`）
