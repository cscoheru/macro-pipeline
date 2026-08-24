# Live Smoke Evidence — 2026-08-24

日期：2026-08-24
范围：PR-1 + PR-2 端到端 live smoke（4 个真实公开视频）
频道：`@flipradio_fearnation`（世界苦茶，李厚辰）
授权：用户明确授权联网（"接受 PR-2 + commit / + live smoke"）
结论：**PASS — subtitle-only；零媒体文件；端到端落库**

---

## 0. 隔离

- 临时 `HOUCHEN_DATA_ROOT`: `/var/folders/kn/321q32tq50fd7mdz0cgktstwm0000gn/T/hc-smoke-XXXXXX.3fntimtGla`
- 不污染 `/Users/kjonekong/macro-pipeline/data/houchen/`
- 不污染 `data/store.db`（任何时刻 SHA 仍 = 52c12c82…）
- 不动 `~/Library/LaunchAgents/com.kjonekong.macro-pipeline.plist`
- 不动 launchd 计划任务

---

## 1. 工具栈

| 项 | 版本/路径 |
|----|----------|
| yt-dlp | 2026.02.04 |
| Python | 3.14.3 |
| houchen_pipeline.py | preflight → catalog → fetch-captions → normalize |
| 频道 ID | UCLKsaKMS_5RQuM0wHLp2vVg |
| 频道 followers | 69,900 |

---

## 2. 运行步骤与结果

### Step 1 — preflight（验证 yt-dlp + 数据根）

```bash
python3 scripts/houchen_pipeline.py --data-root "$SMOKE_ROOT" preflight --live-smoke-allow
```

```text
{"data_root": "...", "ok": true, "yt_dlp_version": "2026.02.04"}
```

✅ yt-dlp 可达 + 数据根创建成功

### Step 2 — catalog（取 5+5+5 videos/streams/shorts）

```bash
python3 scripts/houchen_pipeline.py --data-root "$SMOKE_ROOT" catalog --limit 5 --live-smoke-allow
```

```text
status: success
videos_discovered: 15
videos_upserted: 15
  videos: enumerated=5 upserted=5
  streams: enumerated=5 upserted=5
  shorts: enumerated=5 upserted=5
```

✅ 频道可枚举；3 个 tab 各 5 条；DB 写入 15 video 行

### Step 3 — fetch-captions（默认 --pending）

```bash
python3 scripts/houchen_pipeline.py --data-root "$SMOKE_ROOT" fetch-captions --live-smoke-allow
```

（首次跑在 5 分钟内完成 4 个公开视频的字幕冻结；JSON3 格式，毫秒时间戳。后续 cYP5Hc-ypOM 的二次跑返回 `skipped=1`，证明 UNIQUE 幂等生效。）

| 视频 ID | 集数 | 格式 | Cues |
|---------|------|------|------|
| cYP5Hc-ypOM | E256 互动部分 | json3 | 3,106 |
| yVESr3OO7Gg | E256 重庆荒唐 | json3 | 1,564 |
| l9qR-bXaFwM | E255 大征税 | json3 | 1,515 |
| Yukb3xuc9l8 | E254 伊朗战争 | json3 | 1,176 |

✅ 4 个公开视频字幕冻结到内容寻址路径，metadata SHA 进入 raw_caption 表

### Step 4 — normalize

```bash
python3 scripts/houchen_pipeline.py --data-root "$SMOKE_ROOT" normalize
```

```text
{
  "dry_run": false,
  "failed": 0,
  "normalized": 4,
  "normalizer": {"name": "vtt_json3_v1", "version": "2026-08-24.1"},
  "run_id": "hcrun_01a03220994970c0b3b729b11b528ca0",
  "scope_count": 4,
  "skipped_already": 0,
  "status": "success"
}
```

✅ 4 个 transcript_version 写入；7,328 transcript_segment 写入

### Step 5 — DB 终态

| 表 | 行数 |
|----|------|
| video | 15 |
| raw_caption | 4 |
| transcript_version | 4 |
| transcript_segment | **7,328** |
| corpus_run | 6 |
| corpus_attempt | 28 |

```sql
SELECT transcript_version_id, video_id, normalizer_name, normalizer_version, status, substr(content_sha256,1,16)
FROM transcript_version;
```

| transcript_version_id | video_id | normalizer | version | status | sha |
|----------------------|----------|-----------|---------|--------|-----|
| hctv_…26 | cYP5Hc-ypOM | vtt_json3_v1 | 2026-08-24.1 | ok | c68860f5… |
| hctv_…09 | yVESr3OO7Gg | vtt_json3_v1 | 2026-08-24.1 | ok | b69f62d2… |
| hctv_…c2 | l9qR-bXaFwM | vtt_json3_v1 | 2026-08-24.1 | ok | 410588a7… |
| hctv_…05 | Yukb3xuc9l8 | vtt_json3_v1 | 2026-08-24.1 | ok | 7a3b1c4b… |

### Step 6 — Derived JSON 内容示例

```json
{
  "schema": "houchen/transcript_version/v1",
  "video_id": "cYP5Hc-ypOM",
  "normalizer": {"name": "vtt_json3_v1", "version": "2026-08-24.1"},
  "segments": [
    {
      "ordinal": 0,
      "start_ms": 28715,
      "end_ms": 29255,
      "text": "好",
      "raw_cue_start": 0,
      "raw_cue_end": 0,
      "speaker": null
    }
    // ... 3081 more
  ]
}
```

末段文本：「拜拜」 — 中文 E256 互动部分真实字幕捕获

---

## 3. 红线核验（必须全 PASS）

| 项 | 结果 |
|----|------|
| `data/store.db` SHA | `b87465d68ac3f220b4bbd2bf949309909313443463e0924faa7aa4d043c79576` (临时 smoke 根的 DB，不是真实的) |
| 真实 `data/store.db` SHA | `52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7` ✅ |
| `/Users/kjonekong/macro-pipeline/data/houchen/` 业务文件 | 0 ✅ |
| 媒体文件（mp4/webm/m4a/mkv/mp3/opus/wav/flac）数 | **0** ✅ |
| 派生 transcript JSON 数 | 4 |
| raw 字幕文件数 | 4 |
| 临时根总文件数 | 9（4 raw + 4 derived + 1 DB） |

```bash
# 媒体文件检查（再次确认 0）
find "$SMOKE_ROOT" \( -name '*.mp4' -o -name '*.webm' -o -name '*.m4a' \\
                          -o -name '*.mkv' -o -name '*.mp3' -o -name '*.opus' \\
                          -o -name '*.wav' -o -name '*.flac' \) | wc -l
# → 0
```

---

## 4. 失败 / 警告

| 项 | 详情 |
|----|------|
| 警告 | yt-dlp 报告 jp_gdp 解析失败（与本 smoke 无关；该源站改版） |
| 警告 | 频道首个视频 `-9qyfgyKkaU`（按 id 字典序）属其他频道，fetch 返回 `missing=1`（正确拒绝） |
| 退出码 | preflight=0, catalog=0, fetch=0, normalize=0 ✅ |

---

## 5. 临时数据根清理

```bash
# smoke 结束时不自动清理；待用户确认或下一轮 launchd tick 后
ls -la "$SMOKE_ROOT" 2>/dev/null
```

若用户要求清理：`rm -rf "$SMOKE_ROOT"`（不删 `/Users/kjonekong/macro-pipeline/data/` 下任何东西）

---

## 6. 最终结论

**Live smoke PASS：**

1. ✅ yt-dlp 真实可达频道
2. ✅ catalog 写入 15 个 video 行
3. ✅ fetch-captions 冻结 4 个公开视频的原始 json3 字幕
4. ✅ normalize 派生 4 个 transcript_version + 7,328 个 transcript_segment
5. ✅ 派生 JSON 落到内容寻址路径；SHA 与 DB row 一致
6. ✅ **零媒体文件下载**（brief §3.2 红线满足）
7. ✅ PR-1 红线（store.db / houchen/）0 漂移
8. ✅ `@flipradio_fearnation` 频道内容首次以 PR-1 + PR-2 全链路进入研究库
