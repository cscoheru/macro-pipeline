# PR-4 — 世界苦茶研究库：Obsidian Research Map (+ FTS5 债清收)

**Date:** 2026-08-24
**Branch:** `feat/houchen-pr4-plan` (planning only; no implementation)
**Status:** Plan awaiting `reviews/PR4_PLAN_AUDIT_*.md`; no code under this PR.
**Source of truth:** `docs/厚辰/世界苦茶研究库/CLAUDE_CODE_IMPLEMENTATION_BRIEF.md` §10 (FTS5) / §11 (Obsidian) / §16 (PR-4) / §13 (idempotency) / §15 (security).

---

## Context

PR-1 (corpus foundation) and PR-3 (claim extraction + concept seeding) are
merged into `main` at `47e4de3`. The corpus is the substrate; PR-4 turns it
into a **research map**: a stable, re-publishable Obsidian vault that an
analyst can navigate to find concepts, claims, and forecast candidates without
re-running the model.

Brief §10 places the **FTS5** layer in PR-2, but PR-2/PR-3 delivered the
transcript/claim/concept tables without the search index. PR-4's plan closes
that gap as **Phase 0** before any vault rendering, because:

- A research map without `search` over transcripts/claims/concepts would be
  one-pass static, defeating brief §10's "find a claim's origin video and
  exact quote" use case.
- A consumer (Obsidian reader or external query) needs the same content
  addressing discipline the brief demands; FTS5 must therefore be a schema
  v4 increment gated by `schema_version` + `_apply_v4()`.
- A pre-Obsidian index lets the `search` CLI become a regression target and
  gives the publish step a deterministic content set to render.

Brief §11 requires the Obsidian side to be **independent** of the macro
insight path: separate Obsidian root, separate env file, separate ledger, and
a VaultWriter implementation that uses the macro library's protocol (PUT →
GET readback → SHA verify) without importing its modules.

PR-4 is therefore two ordered phases inside one PR:

- **Phase 0 — FTS5 substrate (brief §10).** Add the FTS5 virtual tables
  and triggers, a fixed query benchmark, and a `search` CLI command.
- **Phase 1 — Obsidian research map (brief §11).** Add the publish path,
  page renderers, the `publish` CLI command, and stable-regeneration tests.

No code lands under this plan; it defines what will land.

---

## Approach

Mirror PR-1 → PR-3's layered split: schema → migration → paths → business
modules → runner → status → CLI → tests. Keep the macro publisher's
"PUT → GET → SHA" protocol but copy it into a new `houchen_publish*` family
under `lib/`, with its own env (`config/houchen_publish.env`, never
`config/insight.env`) and its own database tables.

**Module-count rationale.** The 8-file ceiling in brief §7.7 has already been
exceeded by PR-3 (13 lib files, justified in `docs/plans/pr3-claim-extraction.md`
+ `reviews/PR3_DELIVERY_2026-08-24.md` §3). PR-4 adds 4 more new modules
on the same grounds:

| New module | Reason it cannot be folded into an existing module |
|---|---|
| `houchen_search.py` | FTS5 query planning + the fixed benchmark suite; the `search` CLI is its only caller. |
| `houchen_render.py` | Pure templating (video / concept / claim / forecast / review-queue pages); no I/O, no DB. |
| `houchen_publisher.py` | VaultWriter protocol implementation; never imports `lib/insight_publisher.py` and never touches `data/store.db`. |
| `houchen_publish_paths.py` | Researcher-side path resolution + content-addressing of rendered pages; keeps `houchen_paths.py` from absorbing the publish namespace. |

The split prevents the macro library from being touched, prevents the
renderer from acquiring DB knowledge, and prevents the publisher from
becoming coupled to FTS5 query results.

---

## 1. Schema (v4 increment)

`lib/houchen_schema.py` extends `_V4_*` alongside the existing v1 / v2 / v3
artifacts; `LATEST_VERSION = 4`. New tables and CHECK widening:

### 1.1 FTS5 virtual tables (Phase 0)

Created via ordinary `CREATE VIRTUAL TABLE … USING fts5(...)` statements.
All three reference the parent table's rowid; the corpus stays the single
source of truth.

| Virtual table | Source row | Tokenizer / columns |
|---|---|---|
| `transcript_fts` | `transcript_segment` (one row per segment) | unicode61 (`tokenchars='_‐―'`); columns: `text` (unindexed content); unindexed `transcript_version_id`, `video_id`, `start_ms`, `end_ms`, `ordinal`. |
| `claim_fts` | `claim` (only `status='accepted'`) | unicode61; columns: `claim_text`; unindexed `video_id`, `claim_id`, `claim_type`, `layer`. |
| `concept_fts` | `concept` (status in {'proposed','canonical'}) | unicode61; columns: `canonical_name`, `definition`; unindexed `concept_id`, `status`. |
| `concept_alias_fts` | `concept_alias` | unicode61; columns: `alias`; unindexed `concept_id`, `source`. |

A row-id `trigram` (or n-gram) auxiliary column is **not** added in v1. Per
brief §10 the default unicode tokenizer is used first; the fixed query
benchmark (§8.4) is the gate for any future change.

### 1.2 Triggers (Phase 0)

| Trigger | Table | Event | Body |
|---|---|---|---|
| `trg_transcript_segment_ai` | `transcript_segment` | AFTER INSERT | INSERT into `transcript_fts(rowid, text, transcript_version_id, video_id, start_ms, end_ms, ordinal)` VALUES (new.rowid, new.text, new.transcript_version_id, new.video_id, new.start_ms, new.end_ms, new.ordinal). |
| `trg_transcript_segment_au` | `transcript_segment` | AFTER UPDATE | UPDATE `transcript_fts` SET text=new.text WHERE rowid=old.rowid. |
| `trg_transcript_segment_ad` | `transcript_segment` | AFTER DELETE | INSERT INTO `transcript_fts`(transcript_fts, rowid, text, …) VALUES('delete', old.rowid, old.text, …). |
| `trg_claim_ai / au / ad` | `claim` | INSERT / UPDATE / DELETE | Same shape, restricted to `status='accepted'`. Reinsert after a status flip from `needs_review` → `accepted` is supported. |
| `trg_concept_ai / au / ad` | `concept` | INSERT / UPDATE / DELETE | Same shape, includes both `proposed` and `canonical`. |
| `trg_concept_alias_ai / au / ad` | `concept_alias` | INSERT / UPDATE / DELETE | Same shape. |

The trigger set is mirrored in `lib/houchen_schema._V4_FTS_TRIGGERS`; each
trigger's table + event + body is part of `validate_schema()` so a v3 → v4
migration that fails to install a trigger is rejected before
`schema_version=4` is written.

### 1.3 Publish ledger (Phase 1)

| Table | Notes |
|---|---|
| `rendered_page` | `rendered_page_id` PK, `page_kind` CHECK IN ('video','concept','claim','forecast','review_queue','coverage'), `page_key` TEXT, `render_sha256` TEXT NOT NULL, `template_version` TEXT, `prompt_version` TEXT NULL, `model_id` TEXT NULL, `created_at` TEXT, `attempt_id` TEXT REFERENCES `corpus_attempt(att_id)`. UNIQUE (`page_kind`, `page_key`, `template_version`). |
| `publish_record` | `publish_id` PK, `page_id` REFERENCES `rendered_page`, `vault_path` TEXT NOT NULL, `vault_sha256` TEXT NOT NULL, `status` CHECK IN ('pending','put_ok','readback_ok','published','failed'), `error_class` TEXT, `attempted_at` TEXT, `published_at` TEXT, `att_id` REFERENCES `corpus_attempt(att_id)`. UNIQUE (`page_id`, `vault_path`). |
| `publish_run` | `run_id` PK, `started_at` TEXT, `finished_at` TEXT, `status` CHECK IN ('success','partial','failed'), `summary_json` TEXT. |

The macro insight ledger is **not** extended. These three tables live in
`houchen.sqlite3` only; `data/store.db` keeps its schema untouched.

### 1.4 v3 CHECK widening (audit-style)

`corpus_run.kind` widens to include `'publish'`, `'search'`,
`'concept_seed_render'`. `corpus_attempt.stage` widens the same way.
`corpus_attempt.outcome` widens to include `publish_failed`,
`search_failed`, `render_failed`. No behavior is changed for the v3
outcomes.

---

## 2. Migrations / Paths

### 2.1 Migration (`lib/houchen_migrations.py`)

`_apply_v4()` follows the v3 pattern:

```
BEGIN IMMEDIATE
ver = MAX(schema_version.version)
if ver >= 4 and validate_schema(...): COMMIT; return
if ver < 3: ROLLBACK; raise("cannot apply v4 on <v3")
for stmt in houchen_schema._V4_STATEMENTS: conn.execute(stmt)
for trigger in houchen_schema._V4_FTS_TRIGGERS: conn.execute(trigger)
if not validate_schema(...): ROLLBACK; raise("schema invalid after v4")
INSERT INTO schema_version(version, description) VALUES (4, "PR-4: FTS5 + publish ledger")
COMMIT
```

### 2.2 Paths (`lib/houchen_paths.py` / `houchen_publish_paths.py`)

- `houchen_publish_paths.publish_root() → <data_root>/publish/`
  - `publish_root()/render/<template_version>/<page_kind>/<page_key>.md`
  - `publish_root>/published/<vault_path>.sha256`
  - `publish_root>/obsidian_index.json` (per-render page registry; lets the
    readback test detect orphaned published pages).
- `houchen_paths.env_path() → <repo>/config/houchen_publish.env` (mode 0600;
  never auto-created; missing file = `publish` CLI exits 2 with a remediation
  message).
- `houchen_paths.assert_no_symlink_components` is reused on every publish
  root + subdirectory. The PR-1 ancestor-walk carve-out is unchanged.

### 2.3 Env isolation

`config/houchen_publish.env` (mode 0600, never committed) holds:

```
HOUCHEN_PUBLISH_BASE_URL=https://127.0.0.1:27123
HOUCHEN_PUBLISH_API_TOKEN=...
HOUCHEN_PUBLISH_VAULT_PREFIX=Research/世界苦茶/
HOUCHEN_PUBLISH_TIMEOUT=15
HOUCHEN_PUBLISH_DRY_RUN_ONLY=1   # default; flips to 0 only with operator
```

The macro `config/insight.env` is **never** read; the new module rejects
`HOUCHEN_*` (macro) names and accepts only `HOUCHEN_PUBLISH_*`. A `--dry-run`
flag is the default; no real PUT/GET ever happens without an explicit
`--apply --operator-authorized` opt-in (operator authorization is logged in
`publish_run.summary_json`).

---

## 3. Module split + >8 file justification

PR-4 module plan (incremental over PR-3's 13 lib files):

| New module | LOC est. | Single responsibility |
|---|---:|---|
| `lib/houchen_search.py` | ~250 | Build FTS5 MATCH expressions from a typed query object; run against `transcript_fts`/`claim_fts`/`concept_fts`; return ranked rows with provenance joins. Pure SQLite + dataclasses. |
| `lib/houchen_render.py` | ~500 | Jinja2-free, f-string Markdown rendering of 5 page kinds; deterministic sort order; SHA-256 over the rendered bytes. No I/O, no DB, no network. |
| `lib/houchen_publisher.py` | ~250 | PUT → GET → SHA verify against a `VaultWriter`; transitions `publish_record.status`; never imports `lib/insight_publisher.py`. |
| `lib/houchen_publish_paths.py` | ~80 | Researcher-side path resolution; content-addressed render naming; VaultWriter `vault_path` composition. |

Existing modules extended:

| File | Change |
|---|---|
| `lib/houchen_schema.py` | Add `_V4_*`; widen v3 CHECKs for `'publish'`, `'search'`. |
| `lib/houchen_migrations.py` | Add `_apply_v4()`. |
| `lib/houchen_paths.py` | Add `env_path()` + assertion that the new env file is not a symlink. |
| `lib/houchen_status.py` | Add `publish_state` and `search_index_size` buckets. |
| `lib/houchen_runner.py` | Add `run_search`, `run_render`, `run_publish`. |
| `scripts/houchen_pipeline.py` | Add `search`, `render`, `publish` subcommands. |

Total lib files: 17 (PR-3 = 13, +4 = 17). The §7.7 ceiling was already
broken in PR-3; PR-4 widens it for the same reasons. The justification is
the brief's "split when needed, document why" rule and is recorded in this
plan header.

---

## 4. Publisher adaptation (brief §11, "PUT → GET → SHA")

The new `houchen_publisher.publish_page(*, page_id, vault_writer, actor)`:

1. Verify `rendered_page.status='pending'`. Reject with `invalid_state` if
   not (an already-published page returns `True` and is a no-op; this
   matches `lib/insight_publisher.publish` semantics).
2. Open the render file (`publish_root()/render/<tv>/.../page.md`), compute
   SHA-256; reject if mismatch.
3. `vault_writer.put_pipeline(vault_path, content)`. Map any exception to
   `put_failed` (retryable).
4. `vault_writer.get_pipeline(vault_path)`. Compare SHA-256; reject on
   mismatch as `readback_mismatch` (retryable).
5. Insert/Update `publish_record.status='published'` and the
   `publish_run` ledger row; commit.
6. On any raised `PublishError`, advance `publish_record.status='failed'`,
   record `error_class`, and return False. The next `publish` run is
   idempotent and retries the same content to the same path.

`VaultWriter` is a callable with two methods; tests use a `FakeVaultWriter`
that records the last PUT + GET and lets tests inject SHA mismatches, network
errors, and "GET returns None" cases. The real `ObsidianLocalRestWriter` is
implemented in this PR but is **never auto-invoked**: it requires
`HOUCHEN_PUBLISH_DRY_RUN_ONLY=0` AND `--apply --operator-authorized`.

---

## 5. Page template inventory (Phase 1)

| Page kind | Source rows | Required fields (machine-readable) | Human sections |
|---|---|---|---|
| `video` | one per `video` (after `validated`) | YouTube URL, date, `transcript_version_id`, `analysis_run_id`, `prompt_version`, accepted claim count, rejected claim count, needs-review count, link to concept page(s) referenced, link to forecast page(s) referenced. | "机器提取 / 已校验 / 人工复核" status callout; analysis provenance; claim list with exact-quote + timestamp link. |
| `concept` | one per `concept` (status `proposed` or `canonical`) | `concept_id`, `canonical_name`, `domain_slugs`, `first_seen_at`, `last_seen_at`, every `concept_source` row, every `claim_concept` row joined to `claim` + `claim_source` ordered by `transcript_segment.start_ms`. | Three ordered sections: **Canonical definition** (concept_source.role='canonical_definition'), **Speaker uses** (role='speaker_definition', 'usage'), **System analyses** (claim rows where `claim.layer='system_evaluation'`); callout separating "model" from "human". |
| `claim` | one per `accepted claim` (only if `brief §11.claims.scale = per-claim`; default rollup into `video` and `concept` pages) | claim_id, claim_text, claim_type, layer, speaker, exact_quote, timestamp_url, transcript_version_id, raw_caption_sha256. | Exact-quote block, source-time link, layer status callout. |
| `forecast` | one per `claim_id` with ≥1 `forecast` row | forecast_id, time_window_start/end, outcome_condition, status. | Time-window table; "candidate" badge. |
| `review_queue` | one per `corpus_run` of `kind='validate'` with non-zero `needs_review` count | run_id, started_at, summary, per-rule reject count. | Brief "needs review" manifest; the macro library never writes to it. |
| `coverage` | one per `status` snapshot | schema_version, claim_outcomes, concept_state, analyze_scope, transcript_state. | Reproduce `coverage_markdown` plus "next render SHA" footer. |

Sort order is always `(start_ms, ordinal, claim_id)`; renames are forbidden
between identical inputs.

---

## 6. Runner + CLI

| Command | Action | Idempotency |
|---|---|---|
| `search --kind {transcript,claim,concept} --q TEXT [--limit N] [--json]` | Run a fixed-benchmark query; print ranked rows with provenance. | Read-only. |
| `render --kind {video,concept,forecast,review_queue,coverage} [--key KEY]` | Build Markdown via `houchen_render`; write to `publish_root()/render/<tv>/...`. Set `rendered_page.status='pending'`. | UNIQUE (`page_kind`, `page_key`, `template_version`): re-render is byte-identical; `render_sha256` does not change. |
| `publish [--kind …] [--key KEY] [--dry-run] [--apply --operator-authorized]` | Iterate `rendered_page WHERE status='pending' AND render_sha256 unchanged`; PUT → GET → SHA via `houchen_publisher.publish_page`. | UNIQUE (`page_id`, `vault_path`); publish_record row only advances after readback hash match. |
| `status --json` (extended) | Add `publish_state` and `search_index_size` buckets. | Read-only. |
| `coverage --json` (extended) | Add `publish_state` and `search_index` blocks. | Read-only. |

All write commands honor `--dry-run` (brief §14). `--apply
--operator-authorized` is the only path that flips
`HOUCHEN_PUBLISH_DRY_RUN_ONLY=0` for a single run; the published Vault
content is logged into `publish_run.summary_json` with operator actor.

Exit codes follow the existing PR-1 contract: 0 ok, 1 runtime, 2 usage /
config, 3 partial, 4 data-root config error.

---

## 7. Fixtures + test matrix

### 7.1 Fixtures

- `scripts/houchen_fixtures/fake_vault_writer.py` — records PUT/GET;
  injectable for SHA-mismatch, network error, "GET returns None".
- `scripts/houchen_fixtures/fixed_query_set.py` — 12–20 Chinese +
  English queries with expected hit IDs (gated from brief §10's
  research-question list).
- `scripts/houchen_fixtures/sample_pages.py` — minimal seed corpus
  producing one `video`, one `concept`, one `claim`, one `forecast`
  page so the renderer has non-empty inputs.

### 7.2 Tests (added, not modified)

| File | Tests | Focus |
|---|---:|---|
| `scripts/test_houchen_search.py` | ≥ 25 | FTS5 index refresh, MATCH query against `transcript_fts`/`claim_fts`/`concept_fts`/`concept_alias_fts`, fixed query benchmark, --limit + --kind flags. |
| `scripts/test_houchen_render.py` | ≥ 30 | Determinism: same input → same SHA; layer separation; status callout strings; "no full raw subtitle embedded"; "model analyses" never co-mingled with `speaker_statement` rows. |
| `scripts/test_houchen_publisher.py` | ≥ 20 | PUT → GET → SHA happy path; SHA mismatch → `readback_mismatch` and `publish_record.status='failed'`; network error → retryable; already-published no-op; `HOUCHEN_PUBLISH_DRY_RUN_ONLY=1` short-circuits before any PUT. |
| `scripts/test_houchen_pipeline.py` (append) | ≥ 12 | CLI: `search`/`render`/`publish` dry-run zero writes; `--apply --operator-authorized` flag; env file missing → exit 2; FTS5 absence → exit 2. |
| `scripts/test_houchen_schema.py` (append) | ≥ 10 | v4 tables, FTS5 triggers, `validate_schema` rejects missing/wrong triggers, `--no-fts5` sqlite build is rejected. |
| `scripts/test_houchen_macro_isolation.py` (append) | ≥ 5 | After `render` + `publish` the macro tree (`store.db`, `insights/`, `snapshots/`, `state.json`, `ledger.sqlite`, `macro.db`, `config/`, `logs/`, `data/houchen/`) is byte- and mtime-identical. |

### 7.3 Acceptance gate per brief §9 / §10 / §11 / §16

- **§9.3 hard validator** still rejects every illegal candidate; PR-4
  reruns the existing 10-rule suite unchanged.
- **§10 fixed query benchmark** — the 12–20 fixtures must all hit (or
  intentionally miss with a documented reason) before the renderer is
  considered ready.
- **§11 stable regeneration** — re-render twice on the same input, both
  SHA-256 bytes match.
- **§16 PR-4 exit condition** — at least one rendered `concept` page
  links to ≥1 video, ≥1 claim, ≥1 concept_source; re-`publish` is a
  no-op; `publish` failures leave `publish_record.status='failed'` and
  do **not** advance the ledger.

---

## 8. Critical files

| File | Action | LOC est. |
|---|---|---:|
| `lib/houchen_schema.py` | +v4 tables, +FTS5 triggers, +CHECK widening | +220 |
| `lib/houchen_migrations.py` | +`_apply_v4()` | +60 |
| `lib/houchen_paths.py` | +`env_path()` + symlink assertion | +20 |
| `lib/houchen_search.py` | **NEW** | +250 |
| `lib/houchen_render.py` | **NEW** | +500 |
| `lib/houchen_publisher.py` | **NEW** | +250 |
| `lib/houchen_publish_paths.py` | **NEW** | +80 |
| `lib/houchen_status.py` | +`publish_state`, `search_index_size` | +40 |
| `lib/houchen_runner.py` | +`run_search`, `run_render`, `run_publish` | +180 |
| `scripts/houchen_pipeline.py` | +`search`, `render`, `publish` subcommands | +120 |
| `scripts/houchen_fixtures/fake_vault_writer.py` | **NEW** | +120 |
| `scripts/houchen_fixtures/fixed_query_set.py` | **NEW** | +120 |
| `scripts/houchen_fixtures/sample_pages.py` | **NEW** | +120 |
| `scripts/test_houchen_search.py` | **NEW** | +400 |
| `scripts/test_houchen_render.py` | **NEW** | +450 |
| `scripts/test_houchen_publisher.py` | **NEW** | +350 |
| `scripts/test_houchen_pipeline.py` | extend | +200 |
| `scripts/test_houchen_schema.py` | extend | +120 |
| `scripts/test_houchen_macro_isolation.py` | extend | +90 |
| `docs/plans/pr4-obsidian-research-map.md` | **NEW** (this file) | +350 |
| `docs/厚辰/世界苦茶研究库/PR1_HANDOFF.md` | §12 add PR-4 | +40 |

Totals: **17 lib files** (4 new), **5 test files** (3 new + 2 extended),
**3 fixture files** (3 new), **2 docs** (1 new + 1 extended), **~3,950 LOC**
of new code + tests + docs.

---

## 9. Verification commands

```bash
cd /Users/kjonekong/macro-pipeline

# Phase 0 — FTS5
python3 -m pytest scripts/test_houchen_search.py -q
python3 -m pytest scripts/test_houchen_schema.py -k "fts5 or v4" -q
python3 -m pytest scripts/test_houchen_pipeline.py -k "search or render" -q

# Phase 1 — Publisher + render
python3 -m pytest scripts/test_houchen_render.py -q
python3 -m pytest scripts/test_houchen_publisher.py -q
python3 -m pytest scripts/test_houchen_pipeline.py -k "publish" -q

# Full regression (PR-1 → PR-4 cumulative)
python3 -m pytest scripts -q   # expect >= 510 (PR-3 = 314 + new)

# Static compile
python3 -m py_compile lib/houchen_*.py scripts/houchen_pipeline.py

# Red-line + isolation
shasum -a 256 \
  docs/厚辰/不明白访谈厚辰.docx \
  docs/厚辰/重庆上街-厚辰.docx \
  docs/厚辰/世界苦茶研究库/CLAUDE_CODE_IMPLEMENTATION_BRIEF.md \
  docs/厚辰/世界苦茶研究库/CODEX_ACCEPTANCE_PROTOCOL.md \
  docs/厚辰/世界苦茶研究库/ENGINEERING_TEST_PLAN.md
shasum -a 256 data/store.db     # expect 47e4de3d5cf5c1316b7b366f0fa244e735a61c5a
find data/houchen -type f | wc -l # expect 0

# Smoke dry-runs (zero writes)
HOUCHEN_DATA_ROOT=/tmp/hc-pr4 python3 scripts/houchen_pipeline.py search --kind claim --q "转移支付"
HOUCHEN_DATA_ROOT=/tmp/hc-pr4 python3 scripts/houchen_pipeline.py render --kind concept --dry-run
HOUCHEN_DATA_ROOT=/tmp/hc-pr4 python3 scripts/houchen_pipeline.py publish --dry-run
```

A pre-merge run of `test_houchen_macro_isolation.py` with the full PR-4
CLI chain (catalog → freeze → normalize → seed → analyze → validate →
render → publish) must leave the macro tree byte- and mtime-identical.

---

## 10. Out of scope (explicit)

- Real Obsidian REST writes: `--apply --operator-authorized` is implemented
  and tested, but every test uses `fake_vault_writer`; a real-REST live
  smoke requires a separate user authorization.
- Vector retrieval, embeddings, semantic search: brief §10 forbids.
- Macro bridge, macro link candidates, evaluation reads from macro: brief
  §12 / PR-5, separately authorized.
- Web UI, custom frontends: brief §7 "首版无 UI".
- Bulk re-render of all videos: PR-4 render is per-page; full coverage
  page exists but bulk re-render is opt-in.
- Modifying the three Codex baseline documents or the two DOCX inputs.

---

## 11. Risks and mitigations

1. **FTS5 + Chinese tokenization.** Default `unicode61` is known to be
   weak for CJK. The fixed query set is the gate: if recall on the 12–20
   fixtures is materially below what an analyst would accept, a future
   PR may add an n-gram auxiliary column. PR-4 v1 stays with
   `unicode61`.
2. **`HOUCHEN_PUBLISH_DRY_RUN_ONLY=0` leaks a real PUT.** The default
   is 1; the only path that flips it is the explicit `--apply
   --operator-authorized` CLI flag, recorded in `publish_run.summary_json`
   with operator actor. Tests never use the flag.
3. **Macro insight library entanglement.** The `houchen_publish*` modules
   are forbidden from importing `lib/insight_publisher.py` or writing to
   `data/store.db`. A `tests/test_houchen_publisher.py` grep + import
   smoke test enforces the rule.
4. **Schema v4 not portable to non-FTS5 SQLite builds.** `validate_schema`
   rejects a v3 → v4 migration on a SQLite without FTS5; the runner
   exits 2 with a remediation message. A real CI box without FTS5 is
   treated as a configuration error, not a soft warning.
5. **Obsidian prefix collision.** `HOUCHEN_PUBLISH_VAULT_PREFIX` defaults
   to `Research/世界苦茶/`. If a future macro insight article lands at
   the same prefix, both `publish` and macro publishers fail closed
   (different namespaces in the same Obsidian are allowed but planned
   for only via the existing macro side, never via PR-4).
6. **Page count explosion.** `concept` page count = proposed + canonical
   rows. A future proliferation is capped by the same lifecycle rules
   already in `lib/houchen_concept.py`: nothing auto-promotes.

---

## 12. Reuse and isolation

- Reuse: `lib/houchen_quote.exact_quote_in_segment` (brief §8.6 hard gate,
  unchanged), read-only `lib/houchen_status.status/coverage` (additive
  only), brief's "PUT → GET → SHA" protocol (copied, not imported).
- Isolate: `config/houchen_publish.env`; `data/houchen/houchen.sqlite3`;
  `data/houchen/publish/`. Macro `data/store.db`, `data/insights/`,
  `data/snapshots/`, `data/ledger.sqlite`, `data/macro.db` are
  never read or written by PR-4 code.

---

## 13. Acceptance checklist for `reviews/PR4_PLAN_AUDIT_*.md`

- [ ] Phase 0 FTS5 covers `transcript`, `claim`, `concept+alias` (brief §10).
- [ ] `search` CLI is read-only and uses the fixed query set as a gate.
- [ ] `publish` default is dry-run; `--apply --operator-authorized`
      recorded in `publish_run.summary_json`.
- [ ] All new modules do **not** import `lib/insight_publisher.py` and
      do **not** touch `data/store.db`.
- [ ] Page render is deterministic (SHA-identical on re-render).
- [ ] Concept page separates canonical / speaker / system sections and
      never co-mingles `speaker_statement` with model analysis.
- [ ] Macro isolation E2E added in `test_houchen_macro_isolation.py`.
- [ ] No edits to three Codex baseline documents or two DOCX inputs.
- [ ] Real Obsidian live smoke remains a separate user authorization.
- [ ] No vector retrieval, no embedding, no macro bridge.

---

## 14. Plan delivery

- This plan is the only output of `feat/houchen-pr4-plan`.
- No code, no fixtures, no schema migrations land under this plan.
- A `reviews/CC_HANDOFF_2026-08-24.md` section is appended with the
  planning summary, branch, and the request for Cursor to issue
  `reviews/PR4_PLAN_AUDIT_*.md`.
- Cursor's audit must be accepted and the user must say "启动 PR-4 实现"
  before any code lands.
