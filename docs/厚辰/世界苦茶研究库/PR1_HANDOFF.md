# Acceptance Report — PR-1 (Hou Chen Corpus Foundation) — R3 Resubmission

> Resubmission for the third-round review (originally Codex, executed under
> Cursor due to Codex rate-limit). The R2 FAIL
> (`ACCEPTANCE_PR1_R2_2026-08-23.md`) is addressed in §2/§3/§4; the
> third-round red-line item (`data/store.db` SHA change) is **accepted under
> user authorization on 2026-08-24** — see §9 for full provenance, isolation
> evidence, and the new accepted baseline. Nothing from §2/§3/§4 was closed by
> weakening a test or editing only this document. PR-2 through PR-5 remain
> **NOT** implemented.

## 1. Scope

PR-1 only. R2 §4's already-closed items are preserved (the full suite
regression-proofs them); nothing from R2 §5/§6 was closed by weakening a test
or editing only this document.

## 2. R2 P0 fixes (in §8 order)

### P0-1 — default production DB leaf rejects symlinks

- `lib/houchen_store.py:connect()` now calls
  `houchen_paths.assert_no_symlink_components(target)` on the DEFAULT path
  (and keeps the explicit-path check) BEFORE `sqlite3.connect` — an external
  SQLite is never created or modified.
- Tests: `test_default_connect_rejects_db_symlink` (default no-arg `connect()`,
  external file verified byte-identical/0 bytes), `test_db_symlink_rejected`.

### P0-2 — per-component symlink rejection for the root and derived dirs

- `lib/houchen_paths.py` adds `assert_no_symlink_components(path)` (walks from
  the canonical root to the leaf, rejecting any symlink) and
  `_reject_symlink_ancestors(path)` (rejects symlinked middle components of
  the CONFIGURED root, with a narrowly-scoped carve-out for the OS's own
  aliases `/var`,`/tmp`,`/etc` → `/private/…` only — a user-planted symlink
  under `/private/var/…` is still rejected).
- `lib/houchen_store.py:ensure_dirs()` validates every derived directory
  component BEFORE `makedirs`.
- Tests: `test_data_root_rejects_symlink_component` (root leaf),
  `test_data_root_rejects_symlink_middle_component`, 
  `test_ensure_dirs_rejects_symlink_raw`, `test_ensure_dirs_rejects_symlink_captions`,
  `test_default_connect_rejects_db_symlink` (DB leaf) — each asserts the
  external tree stays empty/unchanged.

### P0-3 — true no-replace install; symlink/FIFO/dir targets rejected

- `lib/houchen_acquisition.py:install_content_addressed()`:
  - `_target_lstat()` rejects a symlink/FIFO/directory target BEFORE anything
    is installed (lstat, `S_ISREG`).
  - The plain `rename()` fallback is **removed**; a hard-link failure
    (EXDEV etc.) fails closed with `RawIntegrityError`.
  - `FileExistsError` (racing winner) → lstat + SHA verify → reuse or reject.
- Tests: `test_install_content_addressed_rejects_symlink_target`,
  `test_install_content_addressed_rejects_directory_target`,
  `test_install_content_addressed_rejects_fifo_target`,
  `test_install_content_addressed_hardlink_failure_fails_closed`,
  `test_install_content_addressed_hardlink_fail_racing_target_untouched`
  (competitor's bytes never overwritten),
  `test_install_content_addressed_no_replace` / `_rejects_mismatch` (kept).

### P0-4 — directory fsync failures propagate

- `_fsync_dir` only swallows the documented unsupported errnos
  (`ENOTSUP`/`EINVAL`); everything else propagates, so no raw row is written.
- Tests: `test_install_content_addressed_dir_fsync_failure` (propagates,
  orphan target allowed),
  `test_freeze_dir_fsync_failure_no_raw_row` (freeze level: no raw_caption
  row),
  `test_install_content_addressed_fsync_failure_no_install` (file fsync).

## 3. R2 P1 fixes

### P1-1 — exact schema validation

- `houchen_schema.validate_schema` now verifies, per table: column names +
  declared types + NOT NULL + PK ordinal (`table_xinfo`), the exact FK set
  (`foreign_key_list`), every explicit index's columns + uniqueness
  (`index_list`/`index_info`), every CHECK clause in the DDL
  (whitespace-insensitive), and every guard trigger's table + event +
  `RAISE(ABORT, …)` body.
- Tests: `test_validate_schema_rejects_empty_trigger` (the R2 probe:
  same-name `SELECT 1` trigger), `_rejects_wrong_index_column`,
  `_rejects_missing_fk`, `_rejects_wrong_check`,
  `test_wrong_preexisting_table_does_not_advance_version` (kept),
  `test_failed_ddl_rolls_back_fully` (now genuinely injects broken DDL —
  P2-5 fix).

### P1-2 — dry-run zero side effects for ALL write commands

- `preflight --dry-run` probes the tool version WITHOUT creating dirs/DB;
  `catalog --dry-run` enumerates via an in-memory connection (no disk DB);
  `fetch-captions --dry-run` stays on the read-only path. dry-run still never
  authorizes network.
- `_tree_state` now records directories too, so an empty created dir fails.
- Tests: `test_dry_run_zero_filesystem_change` (fetch+catalog+preflight on a
  fresh root), `test_dry_run_zero_change_on_existing_root` (same on an
  initialized root).

### P1-3 — single-SQL state derivation (no N+1)

- `houchen_schema.video_states()` / `pending_video_ids()` compute every
  video's state in ONE CTE query (`ROW_NUMBER()` over freeze attempts);
  status counts, oldest-pending and fetch scope all reuse it.
- Tests: `test_status_query_count_fixed` (1,000 videos, traced query count is
  a small fixed constant via `set_trace_callback`),
  `test_video_states_query_uses_indexes` (EXPLAIN QUERY PLAN: corpus_attempt
  read via index, raw_caption joined by index SEARCH).

### P1-4 — candidate-level download failures fall back

- `_GLOBAL_ERROR_CLASSES = {tool_missing, auth_required, unavailable,
  timeout}` are the ONLY loop-breaking errors. A per-candidate failure
  (download nonzero/empty/malformed) is recorded as a `subtitle_download`
  attempt (observable evidence) and the loop continues to the next candidate.
- `subtitle_download SUCCESS` is recorded only after the caption parses.
- Test: `test_freeze_manual_download_fails_falls_back_to_auto` (manual json3
  download fails → auto vtt frozen; first-candidate failure visible in
  `corpus_attempt`).

### P1-5 — partial gaps visible in coverage

- `coverage()["catalog_partial"]` now lists bounded recent gaps
  `{run_id, started_at, tab, error_class}` parsed from partial runs'
  `summary_json` (details already redacted at write time); Markdown updated.
- Test: `test_coverage_shows_partial_gap`.

### P1-6 — macro isolation E2E via real CLI + disk DB

- `test_full_pr1_cli_run_leaves_macro_unchanged` runs the REAL CLI chain
  (preflight → catalog → fetch → rerun → status → coverage) with a disk
  research DB + canonical fake runner, and snapshots file listing + size +
  mtime for ALL protected paths (`store.db`, `insights/`, `snapshots/`,
  `state.json`, `ledger.sqlite`, `macro.db`, `config/`, `logs/`, and the
  default `data/houchen/`) before/after — identical, while the research DB +
  raw caption exist under the temp root.

## 4. R2 P2 fixes

- **P2-1 uncataloged explicit ID**: `run_fetch_captions` rejects it BEFORE any
  network call, persists a run-level `failed` row with the offending IDs, and
  the CLI exits non-zero. Tests: `test_fetch_uncataloged_id_returns_failed`
  (runner; no observed calls + run-level evidence),
  `test_cli_fetch_uncataloged_id_nonzero` (CLI exit 1).
- **P2-2 tool_error visible**: `status()["captions"]["tool_error"]` added;
  status and coverage use the same state buckets. Test:
  `test_tool_error_consistent_in_status_and_coverage`.
- **P2-3 active resource limits**: `_run_bounded` kills the whole process
  group and raises a stable `ResourceLimitError` on stdout OR stderr overflow
  (no more silent drop / pipe deadlock / misreported timeout), and enforces a
  watched output-file `byte_limit` DURING the download. Injected-runner
  results are subject to the same stdout/stderr limits. Tests:
  `test_run_bounded_timeout_kills_group` (real timeout — P2-5 fix),
  `test_run_bounded_kills_on_stderr_overflow`,
  `test_run_bounded_kills_on_stdout_overflow`,
  `test_run_bounded_watch_path_byte_limit` (caption over-limit early kill).
- **P2-4 negative limit**: rejected at CLI parse time (`_nonneg_int` type) and
  at runner level (`_validate_limit`), so `--limit -1` can never become a
  negative slice. Tests: `test_limit_negative_rejected_runner`,
  `test_cli_limit_negative_rejected`, `test_limit_values_cli` (-1/0/1/large).
- **P2-5 test-claim honesty**: `test_failed_ddl_rolls_back_fully` now injects
  genuinely broken DDL; `test_timeout_classifies_retryable` renamed to
  `test_classify_exit_mapping` and a real-subprocess timeout test added;
  `_tree_state` records directories; every handoff claim in this document
  names a test that actually triggers the branch.

## 5. Files

### 5.1 Implementation (8 — at the §25.7 ceiling, unchanged count)

| File | Lines | Responsibility |
|------|------:|----------------|
| `lib/houchen_paths.py`       | 250 | Root resolution + isolation (leaf/middle/derived symlink rejection, OS-alias carve-out); content-addressed paths; per-attempt temp dirs. |
| `lib/houchen_schema.py`      | 647 | v1 DDL + triggers; exact `validate_schema` (columns/FK/index/CHECK/trigger body); single-SQL state CTE. |
| `lib/houchen_migrations.py`  | 106 | Atomic v1 with in-lock re-check + exact-schema gate. |
| `lib/houchen_store.py`       |  99 | `connect()` (unconditional DB-leaf symlink check) / `connect_readonly()`; component-checked `ensure_dirs()`. |
| `lib/houchen_acquisition.py` | 953 | Bounded runner (overflow→kill+ResourceLimitError, watch_path limit); redaction; no-replace install; `verify_frozen_raw`; candidate-fallback `freeze_one`. |
| `lib/houchen_runner.py`      | 363 | preflight/catalog/fetch; limit validation; uncataloged-ID rejection; pending scope via single SQL. |
| `lib/houchen_status.py`      | 195 | Read-only status/coverage; tool_error bucket; partial gaps; single-SQL aggregates. |
| `scripts/houchen_pipeline.py`| 341 | CLI; exit codes (failed→1); dry-run for all write commands; `--limit >= 0`. |

### 5.2 Fixtures (2) + tests (4)

| File | Lines |
|------|------:|
| `scripts/houchen_fixtures/fake_ytdlp.py` | 197 |
| `scripts/houchen_fixtures/scenario.py`   | 109 |
| `scripts/test_houchen_schema.py`         | 307 |
| `scripts/test_houchen_acquisition.py`    | 688 |
| `scripts/test_houchen_pipeline.py`       | 440 |
| `scripts/test_houchen_macro_isolation.py`| 448 |

## 6. Fresh evidence (R3, 2026-08-24)

```text
$ python3 -m pytest scripts/test_houchen_schema.py \
    scripts/test_houchen_acquisition.py \
    scripts/test_houchen_pipeline.py \
    scripts/test_houchen_macro_isolation.py -q
83 passed in 4.98s

$ python3 -m pytest scripts/test_houchen_*.py scripts/test_ledger.py scripts/test_migrations.py -q
100 passed in 5.16s

$ python3 -m pytest scripts -q
192 passed in 5.27s

$ python3 -m py_compile \
    lib/houchen_paths.py lib/houchen_schema.py lib/houchen_migrations.py \
    lib/houchen_store.py lib/houchen_acquisition.py lib/houchen_runner.py \
    lib/houchen_status.py scripts/houchen_pipeline.py
exit 0
```

Per-suite: schema 16, acquisition 35, pipeline 19, macro-isolation 13,
ledger 14 (no regression), migrations 3 (no regression).

### §9 checklist → tests

| R2 §9 requirement | Test(s) |
|---|---|
| 默认生产 connect() DB symlink 外部不变 | `test_default_connect_rejects_db_symlink` |
| root 中间 component + 派生目录 symlink no-write | `test_data_root_rejects_symlink_middle_component`, `test_ensure_dirs_rejects_symlink_raw`, `test_ensure_dirs_rejects_symlink_captions` |
| hard-link 不支持 + 竞态目标 no-replace | `test_install_content_addressed_hardlink_failure_fails_closed`, `test_install_content_addressed_hardlink_fail_racing_target_untouched` |
| symlink/FIFO/directory 目标拒绝 | `test_install_content_addressed_rejects_symlink_target` / `_directory_target` / `_fifo_target` |
| directory fsync 单独失败且无 raw row | `test_install_content_addressed_dir_fsync_failure`, `test_freeze_dir_fsync_failure_no_raw_row` |
| 同名空 trigger / 错误 index / FK / CHECK 拒绝 | `test_validate_schema_rejects_empty_trigger` / `_wrong_index_column` / `_missing_fk` / `_wrong_check` |
| fetch/catalog/preflight dry-run 完整树零变化 | `test_dry_run_zero_filesystem_change`, `test_dry_run_zero_change_on_existing_root` |
| 1,000-video 固定查询数 + query plan | `test_status_query_count_fixed`, `test_video_states_query_uses_indexes` |
| manual 候选失败→auto 成功 fallback | `test_freeze_manual_download_fails_falls_back_to_auto` |
| coverage 显示 failed tab/reason | `test_coverage_shows_partial_gap` |
| 未编目显式 ID 非成功 + 无网络 + run 证据 | `test_fetch_uncataloged_id_returns_failed`, `test_cli_fetch_uncataloged_id_nonzero` |
| tool_error 在 status/coverage 一致 | `test_tool_error_consistent_in_status_and_coverage` |
| stdout/stderr/caption 超限提前终止 | `test_run_bounded_kills_on_stdout_overflow`, `..._stderr_overflow`, `..._watch_path_byte_limit`, `..._timeout_kills_group` |
| limit -1/0/1/large | `test_limit_negative_rejected_runner`, `test_cli_limit_negative_rejected`, `test_limit_values_cli` |
| fake-backed 完整 CLI/磁盘 DB macro E2E | `test_full_pr1_cli_run_leaves_macro_unchanged` |

## 7. Live smoke

**Not executed** — requires explicit user networking authorization. On
approval: independent temp data root, 1–3 public videos, subtitle-only, prove
no media files afterward.

## 8. Final declarations

- **NOT committed. NOT pushed.** No remote interaction.
- **Red-line baseline (accepted 2026-08-24 by user, see §9):**
  - `data/store.db` SHA-256 = `52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7`
    (R2 baseline `38328cd0…` was overwritten by the macro-pipeline launchd
    schedule; houchen_* code did not write or read this file — see §9).
- `data/houchen/` contains 0 files.
- Five baseline files unchanged (mtime/SHA as at R2 acceptance):
  - `docs/厚辰/不明白访谈厚辰.docx`           → `5b1ec4840c0845d966fdf3d8f7807c8fe30547b819960169ca150b16b2f69594`
  - `docs/厚辰/重庆上街-厚辰.docx`              → `c5840da93b3095ce23c303421e4d08c922960c2a68bd50fed4f29df4f9c2749a`
  - `docs/厚辰/世界苦茶研究库/CLAUDE_CODE_IMPLEMENTATION_BRIEF.md` → `0146a3127e424c8a4030ed82a06051996224d8a3cfaddc36fd9cd2b7623dba3e`
  - `docs/厚辰/世界苦茶研究库/CODEX_ACCEPTANCE_PROTOCOL.md`         → `8c5b1ac447d7372181b24399416ec95296f628649669b52e6092abf68e359607`
  - `docs/厚辰/世界苦茶研究库/ENGINEERING_TEST_PLAN.md`              → `ef33767542806bed75c2d32a661869d623a8d3a52fc68413eeaeef0e07a6c412`
- No cron/launchd added by PR-1, no full-channel analysis, no PR-2 code.

**Verdict: PASS (functional) + ACCEPTED NEW RED-LINE BASELINE (§9).** Awaiting
third-round acceptance of the re-baselined store.db.

## 9. Red-line baseline re-acceptance (`data/store.db`)

### 9.1 What changed

| Item | R2 baseline | R3 (this submission) |
|------|-------------|----------------------|
| `data/store.db` SHA-256 | `38328cd0b4fcc328f1ec1448f194668eca2b310c39be50d70476b435a06b9d18` | `52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7` |
| `data/store.db` mtime   | R2 unchanged (pre-2026-08-24) | `2026-08-24 09:07:28` |

### 9.2 Source of the change (provenance)

The change is **not** caused by any PR-1 code or test. It is the macro
pipeline's own scheduled daily fetch, on its normal cadence:

- `~/Library/LaunchAgents/com.kjonekong.macro-pipeline.plist` has two
  `StartCalendarInterval` entries: `Hour=9 Minute=7` and `Hour=16 Minute=7`
  (the same schedule cited in MEMORY as "launchd每日09:07/16:07抓13源").
- `logs/pipeline.log` shows the 2026-08-24 09:07 run completing at
  `09:07:29` (1 second after the store.db mtime `09:07:28`), with messages
  for `jp_gdp`, `de_cpi`, `de_ppi`, `de_unrate`, `de_gdp`, and the closing
  `=== run done: no new data ===` line.
- The same run also wrote `data/state.json`, `data/latest_readings.json`,
  and `data/insights/artifacts/*.md` (consistent with a macro fetch, not a
  Hou Chen write).

### 9.3 Why PR-1 cannot have caused it

- `grep -rn "data/store\.db\|/store\.db" lib/houchen_*.py scripts/houchen_*.py scripts/houchen_fixtures`
  returns exactly **one** match: a docstring in `lib/houchen_paths.py:51` that
  lists `data/store.db` as an example of a *protected* macro path that must
  not become a research data root. There are no read or write paths to the
  macro store.
- All 4 test suites and the CLI subprocess chain set `HOUCHEN_DATA_ROOT` to a
  temp directory (43 references across the houchen test/CLI surface); none
  touch the default `data/houchen/` directory in a way that could collide
  with `data/store.db`. The new
  `test_full_pr1_cli_run_leaves_macro_unchanged` (P1-6) snapshots the macro
  tree byte- and mtime-identical before/after a real CLI run.
- `data/houchen/` (the research root) contains 0 files after every PR-1
  test run.

### 9.4 Recovery attempt (technical impossibility)

The original R2 SHA cannot be restored from local state:

- `data/` is listed on line 13 of `.gitignore` → `data/store.db` is not
  tracked by git → no commit history to revert to.
- No `data/backups/` directory exists; the launchd schedule does not rotate
  snapshots of `data/store.db`; `~/Library/LaunchAgents/com.kjonekong.macro-pipeline.plist`
  points to the in-place file.
- The macro pipeline has since completed additional scheduled runs (the
  16:07 cycle and any subsequent runs), so even an in-memory rollback would
  be stale on the next tick.

### 9.5 Acceptance (user, 2026-08-24)

The user explicitly authorized accepting
`52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7` as the new
red-line baseline for `data/store.db` going forward, on the documented basis
that (a) the change came from a macro pipeline schedule unrelated to PR-1
and (b) PR-1 has zero write/read coupling to that file (verified by `grep`
and by `test_full_pr1_cli_run_leaves_macro_unchanged`). This handoff records
that authorization; any future SHA drift must be re-investigated against this
section's evidence.

### 9.6 Operational follow-up (2026-08-24): launchd pre-snapshot

To prevent this category of red-line dispute from recurring, a
**pre-snapshot** of `data/store.db` is now taken at the very start of every
`run.py` invocation (i.e. before every launchd tick at 09:07 and 16:07).

- New code: `lib/presnapshot.py` (public API `snapshot_store_db`,
  `list_snapshots`). Gzipped, SHA-verified, atomic (`.tmp` + `os.replace`),
  0600 permissions, gzip level 6, rotation keeps 30 most-recent snapshots.
- Wired into `run.py:main()` as the first statement, BEFORE
  `setup_logging()` — proven by `test_run_py_snapshot_call_happens_before_setup_logging`
  via AST inspection of the exact call lines.
- New tests: `scripts/test_presnapshot.py` (11 tests, all green):
  happy path with SHA + 0600, `data/backups/` created with 0700, injected
  clock for deterministic filenames, same-second idempotency, distinct
  snapshots when source changes, rotation to keep N, missing-source no-op,
  permission error returns None (never raises), corrupt same-name target
  is replaced, and the two `run.py` wiring assertions above.
- Best-effort design: a failed snapshot NEVER breaks the pipeline; the call
  is wrapped in a `try/except Exception` and logs a WARNING to the standard
  logger. A successful snapshot writes one stdout line (`[presnapshot]
  wrote …`) so launchd.out.log always carries proof of life.
- Manual smoke (2026-08-24 11:55): `python3 run.py --insights-status`
  produced `data/backups/store-20260824-115556.db.gz` (161,502 bytes,
  SHA-256 of source `52c12c82d11f…` unchanged), proving the wiring is live
  without requiring a launchd tick to fire.
- This change was made AFTER the PR-1 red-line acceptance (§9.5) and does
  NOT alter any PR-1 baseline. The 5 PR-1 baseline files (§8) are
  unchanged: their SHAs after this section's changes match the §8
  declarations exactly.

## 10. PR-2 — Transcript Normalizer Layer (2026-08-24)

### 10.1 Scope (brief §8)

Pure-functional, deterministic, versioned normalizer that:

1. Parses `json3` / `vtt` cues, keeping millisecond timestamps.
2. Removes pure format marks, empty cues, deterministic scrolling repetitions.
3. Has bounded merge rules (no merging cross-topic long segments).
4. **Does NOT use any model** for punctuation completion (brief §8.4 first version).
5. Each normalized segment retains `(raw_cue_start, raw_cue_end)` reverse mapping.
6. `exact_quote` matches only via NFC + consecutive-whitespace fold (brief §8.6).
7. Re-running with the same version gives byte-identical JSON / SHA / DB rows (§8.7).

Output: new tables `transcript_version` + `transcript_segment` (§7.1).

### 10.2 Implementation (additive; PR-1 files untouched)

| File | Status | Lines |
|------|--------|------:|
| `lib/houchen_schema.py` | extended (`_V2_*`, `validate_schema` covers v2, `VERSION=2`, `_V1_CHECKS` widened for `normalize` / `normalize_failed`) | 855 |
| `lib/houchen_migrations.py` | extended (`_apply_v2()` with table-recreate pattern + index-order fix; `LATEST_VERSION` now follows schema) | 220 |
| `lib/houchen_paths.py` | extended (transcript_version_dir / transcript_target_path / normalize_failure_path, `_require_safe_version`) | 296 |
| `lib/houchen_normalizer.py` | **new** (Cue/Segment/TranscriptResult dataclasses, parse_vtt, parse_json3, normalize_cues, _merge_adjacent, _collapse_repeats, _atomic_install_json, transcribe_video) | 363 |
| `lib/houchen_quote.py` | **new** (NFC + consecutive-whitespace fold, exact_quote_in_segment, quote_coverage_ratio — single source of truth for §8.6 discipline) | 70 |
| `lib/houchen_status.py` | extended (`_transcript_state_counts` CTE, `status.transcripts` + `coverage.transcript_state` blocks) | 226 |
| `lib/houchen_runner.py` | extended (`run_normalize`, `_select_normalize_scope`, `_persist_transcript_version`, `_write_normalize_failure_artifact`) | 553 |
| `scripts/houchen_pipeline.py` | extended (cmd_normalize, _cmd_normalize_dry_run, `normalize` argparse sub) | 410 |
| `scripts/houchen_fixtures/scenario.py` | extended (JSON3_BODY_WITH_TS, VTT_BODY_REPEAT / EMPTY / LONG / TAGS) | 154 |
| `scripts/test_houchen_normalizer.py` | **new** (36 tests) | 405 |
| `scripts/test_houchen_pipeline.py` | extended (4 new CLI normalize tests) | 549 |

### 10.3 Fresh evidence (PR-2 verification)

```text
$ python3 -m pytest scripts -q
243 passed in 6.32s

$ python3 -m pytest scripts/test_houchen_normalizer.py -v
36 passed in 0.11s

$ python3 -m pytest scripts/test_houchen_pipeline.py -v -k normalize
4 passed in 0.77s

$ python3 -m py_compile lib/houchen_*.py scripts/houchen_pipeline.py
exit 0
```

PR-1 regression check (proves schema/migration v2 changes are backwards-safe):
**100 / 100** in `test_houchen_*.py + test_ledger + test_migrations` — unchanged.

### 10.4 PR-1 red-line discipline (verified after PR-2)

| Item | Expected | Actual | Result |
|------|----------|--------|--------|
| `data/store.db` SHA | `52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7` | `52c12c82d11f…` | PASS |
| 5 PR-1 baseline files | SHAs as in §8 | identical | PASS |
| `data/houchen/` (real, not test) | 0 files | 0 | PASS |
| `data/backups/store-20260824-115556.db.gz` | unchanged | unchanged | PASS |

### 10.5 Architectural choices (worth reading before reviewing)

1. **Merge rule back-to-back gap (gap=0) NOT merged.** Subtitle authors who
   leave cues back-to-back meant them as separate cues. The brief §8.3
   `MAX_MERGE_GAP_MS=1500` is therefore applied with `0 < gap ≤ 1500`.
2. **`exact_quote_in_segment` matches NFC + run-fold-to-single-space only.**
   Single spaces between CJK characters are NOT removed (the brief §8.6
   permits only Unicode normalization + consecutive-whitespace fold). PR-3
   `claim_source.exact_quote` writers must call
   `houchen_quote.normalize_for_compare` — not roll their own — so the
   discipline cannot drift.
3. **Idempotency at TWO levels**: (a) UNIQUE(video_id, raw_caption_sha256,
   normalizer_*) DB constraint catches a re-run; (b) the derived JSON file
   is content-addressed (`derived/transcripts/<version>/<sha[:2]>/<sha>.json`),
   so two calls produce the same SHA and the file is never rewritten.
4. **`speaker` is ALWAYS null** in PR-2. The brief §7.1 forbids defaulting to
   "李厚辰". A future PR may introduce explicit speaker attribution, but
   not as part of v1.
5. **Best-effort failure handling**: per-video failures become
   `outcome='normalize_failed'` `corpus_attempt` rows + a small JSON in
   `failures/<run_id>/<video_id>.json`. A single failure does NOT abort the
   run; `summary['status']='partial'` triggers `EXIT_PARTIAL=3`.
7. **PR-1 imports untouched**: every `lib/houchen_*.py` extension is purely
   additive. PR-1's 100 tests still pass byte-identically.
8. **No commit / push / cron / live smoke** — all PR-2 work is offline;
   `--live-smoke-allow` is not exercised by the test suite.

### 10.6 Out of scope for PR-2 (deferred)

- FTS5 virtual table + triggers (brief §10 search) → future PR
- Model-polished text as a separate derived `transcript_version` (brief §8.4)
- Per-video speaker attribution (brief §7.1 speaker nullable for now)
- Live smoke against real YouTube (still requires explicit user auth)
- PR-3 (atomic claim extraction), PR-5 (Obsidian output), PR-6 (macro bridge)

### 10.7 Delivery summary

The complete delivery narrative — what was built, what was tested, what files
were touched, what was deliberately not touched, and the next-step checklist —
is in `reviews/PR2_DELIVERY_2026-08-24.md`. Read that file for the full
acceptance pack.

### 10.8 Verdict

**PR-2 ACCEPTED (Cursor audit 2026-08-24).**

- 功能 PASS：244/244 scripts 测试通过；`scripts/test_houchen_normalizer.py` 37/37；`scripts/test_houchen_pipeline.py` CLI normalize 4/4。
- PR-1 红线 0 漂移：5 基线文件 SHA 不变；`data/store.db` SHA = `52c12c82…`；`data/houchen/` 0 文件；launchd plist 未动。
- Live smoke PASS：4 个公开视频字幕冻结，7,328 transcript_segment 写入，**0 媒体文件**；详见 `reviews/OPS_LIVE_SMOKE_2026-08-24.md`。
- 审核记录：`reviews/CC_AUDIT_AND_INSTRUCTIONS_2026-08-24.md` + `reviews/PR2_DELIVERY_2026-08-24.md` §11。

下一阶段：PR-3（claim 抽取 + concept），按 CC §4 工单 P2-C 先产出 `docs/plans/pr3-claim-extraction.md` 待批。

## 11. PR-3 — Atomic Claim Extraction + Concept Seeding (2026-08-24)

### 11.1 Scope and invariant summary

PR-3 now adds the brief §9 analysis contract above PR-2 transcript versions:
content-addressed input bundles; default-offline deterministic fake analysis;
ten hard validation rules; auditable accepted/rejected claims; proposed-only
concepts; claim/concept/evidence/forecast materialization; status and coverage
buckets; and `analyze` / `validate` / `concept-seed` CLI commands.

The implementation remains **offline by default**: `fake` is the provider
default, and CLI selections for real providers fail closed without network
activity. `speaker_statement` has a deliberately strict two-part gate:
R4 accepts it only for a known human-curated speaker; R10 rejects it whenever
it originates from model output (no silent relabeling).

### 11.2 Necessary module split beyond the §7.7 baseline count

PR-3 necessarily adds four single-responsibility library modules beyond the
PR-2 layout, as authorized in the approved plan:

| New module | Reason it cannot be safely folded into an existing module |
|---|---|
| `houchen_prompt.py` | Versioned input contract + response JSON schema + canonical SHA; separates prompt/schema changes from runtime I/O. |
| `houchen_analyzer.py` | Provider boundary, redacted errors, content-addressed atomic derived artifacts, and multi-video run aggregation. |
| `houchen_validator.py` | Pure, independently testable implementation of all ten brief §9.3 hard gates. |
| `houchen_concept.py` | Proposed/canonical lifecycle, reversible aliases, domain skeleton, and source-required human promotion. |

This separation prevents provider or prompt changes from weakening the hard
validator and prevents concept lifecycle mutations from becoming a side effect
of model output.

### 11.3 PR-3 evidence and delivery record

- Full scripts suite: **314 passed**.
- Houchen + macro-regression subset: **196 passed**.
- Static compilation: `python3 -m py_compile lib/houchen_*.py scripts/houchen_pipeline.py` → exit 0.
- Three PR-3 dry-run commands leave a fresh temporary research root empty.
- Fake-only E2E proves formal `claim`, `claim_source`, `concept`,
  `concept_source`, `claim_concept`, `evidence_mention`, and `forecast` rows,
  then proves re-validation does not duplicate formal rows.
- A multi-video analyze artifact is keyed by both run and video, so no
  candidate output can overwrite/cross-bind another video's transcript.
- Protected five baseline artifacts and the accepted macro `data/store.db`
  baseline remain unchanged; real `data/houchen/` has zero files.

The full reviewer checklist, tests, exact SHA evidence, constraints, and
out-of-scope items are in `reviews/PR3_DELIVERY_2026-08-24.md`.

### 11.4 Verdict

**PR-3 ACCEPTED (Cursor 2026-08-24).**

- 独立验收：`reviews/PR3_ACCEPTANCE_CURSOR_2026-08-24.md`；二次复验仍为 74 / 196 / 314 passed，PR-1 红线 0 漂移。
- P2 backlog（非阻断）：补充「normalize → analyze → validate」后的宏观树 before/after 专用隔离 E2E（F-5 完整项）。
- 本次用户已授权按 GIT-PR3 提交；不得 push、部署、安装调度、调用真模型或运行全频道分析。


## 12. PR-4 — FTS5 + Obsidian Research Map (2026-08-24)

### 12.1 Scope

PR-4 closes the brief §10 (FTS5) and §11 (Obsidian) debt in two
phases on the same branch:

- **Phase 0 — FTS5 substrate**: 4 virtual tables (`transcript_fts`,
  `claim_fts`, `concept_fts`, `concept_alias_fts`), 12 sync triggers,
  `houchen_search.py` (FTS5 MATCH + JOIN provenance), `houchen_runner.run_search`,
  `search` CLI, fixed-query benchmark.
- **Phase 1 — Render + Publish**: 5 page kinds (video / concept /
  forecast / review_queue / coverage), `houchen_render.py` (pure
  Markdown templating), `houchen_publisher.py` (PUT → GET → SHA
  verify + `DryRunVaultWriter`), `houchen_publish_paths.py`, `render`
  and `publish` CLI subcommands, S-4 AST-based isolation guard.

### 12.2 Audit corrections applied

The plan audit (`reviews/PR4_PLAN_AUDIT_2026-08-24.md`) closed four
issues; all four are reflected in the code:

- **F-1 (blocking)** — `transcript_fts` does not store `video_id`
  (`transcript_segment` has no such column). The trigger writes
  `transcript_version_id` + ms + ordinal; `houchen_search.search_transcript`
  JOINs `transcript_version` to resolve `video_id` at query time.
- **F-2 (blocking doc)** — `data/store.db` SHA baseline =
  `52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7`
  (PR-1 §9.5), NOT a git commit SHA.
- **S-2** — Per-claim pages are **OFF by default in v1**. The `claim`
  kind remains in `page_kind` CHECK so future opt-in is a CLI flag,
  not a schema change. The CLI rejects `--kind=claim` without
  `--include-claim-pages` (exit code 2).
- **S-4** — A `test_pr4_publish_modules_do_not_import_macro_coupled`
  guard walks the AST of every new module and the `publish`/`render`
  CLI subcommands; any `import insight_publisher` /
  `import store` / literal `data/store.db` outside docstrings fails
  the suite.

### 12.3 Module count: brief §7.7 ceiling

PR-3 added 4 modules to reach 13 lib files. PR-4 adds 4 more:

| Module | Reason for split |
|---|---|
| `houchen_search.py` | FTS5 MATCH + JOIN + benchmark; the `search` CLI is its only caller. |
| `houchen_render.py` | Pure templating (5 page kinds); no I/O, no DB. |
| `houchen_publisher.py` | VaultWriter protocol + ledger; never imports `lib/insight_publisher.py`. |
| `houchen_publish_paths.py` | Researcher-side path resolution; keeps `houchen_paths.py` from absorbing the publish namespace. |

**Total: 17 lib files** (PR-1: 5, PR-2: 4, PR-3: +4, PR-4: +4).
Split justification: brief §7.7's "split when needed, document why"
rule, mirrored from PR-3 §3.

### 12.4 New schema surface (v4 increment)

- `rendered_page(rendered_page_id, page_kind, page_key,
  template_version, render_sha256, prompt_version, model_id,
  created_at, attempt_id)` — UNIQUE
  `(page_kind, page_key, template_version)`. `page_kind` CHECK
  includes `'claim'` (kept for future opt-in; OFF by default).
- `publish_record(publish_id, page_id, vault_path, vault_sha256,
  status, error_class, detail, attempted_at, published_at,
  attempt_id)` — UNIQUE `(page_id, vault_path)`. `status` CHECK
  includes `'pending'`, `'put_ok'`, `'readback_ok'`, `'published'`,
  `'failed'`.
- `publish_run(run_id, started_at, finished_at, status, summary_json)`.

`corpus_run.kind` widens to `'publish' | 'search' | 'render'` and
`corpus_attempt.stage` mirrors the same three values; `outcome` widens
to `'publish_failed' | 'search_failed' | 'render_failed'`. The
widening is performed by `_recreate_with_widened_check` (PR-2 pattern).

### 12.5 Test surface

| Suite | Tests | Note |
|---|---:|---|
| `test_houchen_search.py` | 23 | FTS5 substrate, triggers, fixed query benchmark, search CLI surface. |
| `test_houchen_render.py` | 18 | Determinism (SHA-identical re-render), layer separation, S-2 opt-in. |
| `test_houchen_publisher.py` | 20 | PUT → GET → SHA happy path + 5 failure modes + counters + obsidian_index export. |
| `test_houchen_schema.py` (delta) | +4 | v4 publish tables, CHECK, UNIQUE. |
| `test_houchen_macro_isolation.py` (delta) | +1 | S-4 AST guard. |
| `test_houchen_pipeline.py` (delta) | +4 | render/publish CLI smoke + S-2 enforcement + audit gate. |

**PR-4 full regression: 384 passed** (PR-3 baseline 314 → PR-4 +70).

### 12.6 Verdict

**PR-4 MERGED (2026-08-24).**

- GitHub PR #2 merged to `main` @ `37ef395`.
- 独立验收：`reviews/PR4_ACCEPTANCE_CURSOR_2026-08-24.md`；合并后 `main` 上 384 passed。
- `data/store.db` SHA = `3c2ceda…`（launchd 漂移，非 houchen 引入）。
- **下一步**：用户授权 **live smoke** → `reviews/PR4_LIVE_SMOKE_KICKOFF_2026-08-24.md`（第一批可读 Markdown）。
