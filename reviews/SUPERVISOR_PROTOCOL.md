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

## 每轮（loop tick）

1. 读 `reviews/CC_INBOX.md` + `reviews/SUPERVISOR_STATE.md` + `git log -5`
2. `STATUS=WAIT_CURSOR` → 按工单验收；PASS 则 commit 验收 + 派计划中下一刀 `DO`
3. `STATUS=DO` 且进度在动 → 只更新 STATE，不改工单
4. `STATUS=DO` 且 **≥25min 无 git/文件进展** → 在 STATE 记 stalled，**下一刀不重复派同一工单**；仍不叫用户，除非卡在上表
5. 计划队列清空且无 stalled → INBOX `WAIT_USER` 一句「队列空，两小时后看 STATE」

## 当前计划队列（完成后划掉）

1. [ ] ASR 试点 3 streams 交卷并验收  
2. [ ] 若 PASS：ASR 扩 5 streams（非 shorts、非已有字幕）  
3. [ ] 概念页若 accepted 又增：增量 refresh  
4. [ ] 队列空 → 停 loop
