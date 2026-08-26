# Claude Code — claim 后收尾（概念刷新 + stream publish + videos 抽 claim）

> **签发**：Cursor（2026-08-26 20:43）  
> **触发**：用户「不用等我裁定，除非跑不下去，你自行裁定」  
> **不问用户**；卡住才 `WAIT_USER`

## 自行裁定

| 做 | 不做 |
|----|------|
| 概念页增量 refresh（已授权） | shorts |
| 未 publish 的 stream 视频页进 Obsidian | 全频道 637 catalog（本地语料先收完） |
| MiniMax-M3 抽 **videos** 里 14 支已有字幕、从未 analyze | 云端 ASR；写 `store.db`；`promote_to_canonical` |
| | 空 candidate / `Xp4GBvKBPww` 质量 DEFER 不重跑 |

已有 `analyze` pid → 禁止第二路。禁止 ASR。禁止 DeepSeek。

## A. 概念

挂 accepted claim 的概念：re-render `--from-db`，再 `publish --kind concept --apply --operator-authorized --actor post-claim-catchup --live-smoke-allow`。

## B. 视频页 publish

`publish --kind video --apply --operator-authorized --actor post-claim-catchup --live-smoke-allow`  
Obsidian 不可达则记 DEFER，继续 C。

## C. MiniMax 14 videos

```text
6O8fWfJBnZs
f_jd_j3eEuE
ipCcKnvHHUM
kKk3env0Brg
m2bkSXQ4Pmg
mg_BuWqSL9A
nvMGmlJvKG8
olJKWOuXMlY
qG_gtSj1_Mk
uvdjCakZcmE
v4Ftq5mnhAc
wnn-J3nBnEU
ykNlnY0NaAk
ywAOwF3bxA4
```

每支：analyze MiniMax → validate `|| true` → render。Python：`/usr/local/bin/python3`。

完成后写 `reviews/POST_CLAIM_CATCHUP_REPORT_2026-08-26.md`（无转写、无密钥）。
