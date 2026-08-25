# Guest BumingBai EP-230 Report (2026-08-25)

## 视频登记

| 字段 | 值 |
|------|-----|
| video_id | KLJJuMybVsc |
| channel | 不明白播客 |
| channel_handle | @bumingbai |
| title | EP-230 李厚辰：习近平为何不着急救中国经济？ |
| published | 2026-08-21 |
| duration | 4492s |
| content_kind | video |

**未写入** video_collection_membership（避免混入 streams/videos 计数）

## WPS 导入

- 文件: `data/houchen/asr/audio/不明白访谈厚辰.docx`
- segments: **371**
- format: docx → vtt
- status: success

## 竖切

| 阶段 | 结果 |
|------|------|
| analyze | ✅ success (deepseek) |
| validate | **8 accepted**, 0 rejected |
| render | ✅ rendered |
| publish | ✅ published to `Research/世界苦茶/video/KLJJuMybVsc.md` |

## 第二文件: yVESr3OO7Gg

- 文件: `data/houchen/asr/audio/重庆上街-厚辰.docx`
- 旧 wps_import 已 stale，清理后重导入
- segments: **71**
- 状态: success（per kickoff "不要重分析"，仅做 WPS 导入）

## 红线

- store.db SHA `4a8e409b…` ✅
- 434 tests pass
- 不重做 yVESr3OO7Gg 分析 ✅