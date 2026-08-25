# 事故简报：所谓 data/ 清空（2026-08-25）

> Cursor 复验；用户转发 CC 告警

## 结论

**未发生**仓库 `data/` 全量丢失。CC 看到的是 **错误 data root 下的空库**。

## 证据

| 路径 | 状态 |
|------|------|
| `data/store.db` | 780KB，SHA `4a8e409b…`，mtime 09:07 |
| `data/houchen/houchen.sqlite3` | 33MB，`PRAGMA integrity_check=ok`，129 video / 50 caption |
| `data/houchen/asr/audio/*.webm` | 3× ~358MB，mtime 10:43–10:55 |
| `data/houchen/asr/audio/data/houchen/houchen.sqlite3` | **0 bytes**（误建） |

## 根因（高置信）

相对路径或错误 `HOUCHEN_DATA_ROOT`，在抽音频目录下创建了嵌套：

`…/asr/audio/data/houchen/`

对该空库的检查被当成「主库被清空」。

## 处置

- 勿 rebuild / 勿全量重抓  
- `rm -rf data/houchen/asr/audio/data`  
- 继续 P2b import-transcript；音频已齐，供用户 WPS  
