# PR-3 Delivery & Acceptance Pack — Atomic Claim Extraction + Concept Seeding

**Date:** 2026-08-24
**Scope:** World Bitter Tea Research Library / PR-3
**Implementation state:** Complete locally; **not committed, pushed, deployed, scheduled, or run against a live model**.

> Review entry point: `reviews/PR3_PLAN_AUDIT_2026-08-24.md`.
>
> This file records the implementation evidence required for the next Cursor
> review. It does not replace the immutable brief, acceptance protocol, or
> engineering test plan.

---

## 1. Executive result

PR-3 implements the offline, auditable analysis contract on top of frozen
captions (PR-1) and deterministic transcript versions (PR-2):

1. **Content-addressed analysis input** bundles include the exact normalized
   segments, transcript version, fixed seven-domain skeleton, prompt/schema
   versions, and provider/model identifiers.
2. The default `fake` provider is **fully offline** and deterministic. Real
   provider selections (`anthropic`, `deepseek`, `minimax`) are deliberately
   disabled in PR-3 v1 and return a controlled `analyze_failed` result; they
   do not open a network connection or read `config/insight.env`.
3. A hard validator enforces all ten brief §9.3 rules and records per-item
   reasons. It never silently downgrades a model-produced
   `speaker_statement`.
4. Validation materializes provenance-backed claims plus proposed concepts,
   claim-concept links, evidence mentions, and forecast candidates.
5. The concept lifecycle is intentionally conservative: discovered concepts
   are `proposed`; canonical promotion requires both an explicit human actor
   and a backing `concept_source`.
6. All default tests run against temporary research roots, fake fixtures, and
   fake provider output. No audio/video media is persisted.

---

## 2. Locked constraints verified

| Constraint | Result | Evidence |
|---|---|---|
| Separate corpus DB only | PASS | `houchen_paths.sqlite_path()` remains `<data-root>/houchen.sqlite3`; PR-3 E2E uses a temporary `HOUCHEN_DATA_ROOT`. |
| No macro DB migration/write | PASS | `data/store.db` SHA remains `52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7`; existing macro-isolation tests still pass. |
| No DOCX / 3 Codex baseline edits | PASS | Five protected SHA-256 values unchanged; exact values in §8. |
| Frozen raw caption never updated/deleted | PASS | PR-3 only reads `raw_caption_sha256` through a transcript version; existing immutable-trigger tests pass. |
| No audio/video persistence | PASS | Analysis reads only DB rows + caption-derived transcript JSON; the fake provider has no media/network API. |
| Default test path completely offline | PASS | `provider='fake'` is default; fake fixture deterministic; E2E proves real provider selection fails closed. |
| No automatic concept promotion | PASS | `upsert_proposed_concept()` inserts `status='proposed'`; `promote_to_canonical()` requires actor + `concept_source` ID. |
| No commit / push / deploy / scheduler | PASS | None performed. |

---

## 3. Delivered implementation

### 3.1 Schema & migration (v3)

| File | Change |
|---|---|
| `lib/houchen_schema.py` | Adds schema v3 with `domain`, `concept`, `concept_alias`, `concept_domain`, `concept_source`, `claim`, `claim_source`, `claim_concept`, `reasoning_edge`, `evidence_mention`, `external_evidence`, `evaluation`, and `forecast`; expands run/attempt CHECK values for `analyze`, `validate`, `concept_seed`. |
| `lib/houchen_migrations.py` | Adds atomic `_apply_v3()` and v3 CHECK-recreate support; exact schema validation gates migration completion. |
| `scripts/test_houchen_schema.py` | Covers the 13 new tables and widened run/attempt checks. |

**Audit corrections preserved:**

- **F-1:** seven (not six) fixed domain seeds.
- **F-2:** formal `claim.analysis_run_id` references the successful analysis
  `corpus_run`, not the later validation operational run.
- **F-3:** `concept.canonical_name` is required by the lifecycle helper.

### 3.2 Input, provider, paths, and offline boundary

| File | Change |
|---|---|
| `lib/houchen_paths.py` | Safe paths for content-addressed analysis inputs and per-run artifacts. |
| `lib/houchen_prompt.py` | Versioned prompt/input contract (`2026-08-24.1`, `claim_extraction_v1`), seven-domain input skeleton, canonical JSON SHA-256, output JSON Schema. |
| `lib/houchen_analyzer.py` | Atomic 0600 writes under 0700 parents, signed URL/Bearer/data-root redaction, fake-provider dispatch, per-run **multi-video artifact aggregation**. |
| `scripts/houchen_fixtures/fake_provider.py` | Deterministic offline fixture: one accepted `speaker_reasoning` claim, deliberate R2/R5 rejects, a proposed concept, evidence mention, and forecast. |
| `scripts/test_houchen_analyzer.py` | Content-address stability, 0600/0700 modes, idempotent write, multi-video artifact non-overwrite, provider disablement, redaction, segment projection. |

**Multi-video correctness fix:** a run artifact is now:

```json
{
  "run_id": "...",
  "items": {
    "<video_id>": {
      "input_sha256": "...",
      "transcript_version_id": "...",
      "candidates": { "...": "..." }
    }
  }
}
```

Validation selects by both `run_id` **and** `video_id`, preventing a later
video in an analyze run from overwriting/cross-binding the first video's model
output.

### 3.3 Hard validator (brief §9.3)

| Rule | Enforcement |
|---:|---|
| R1 | Required claim fields; zero ordinals/milliseconds are accepted as valid values, not mistaken for missing fields. |
| R2 | `exact_quote` must match via the sole allowed `houchen_quote.exact_quote_in_segment` NFC + whitespace-fold implementation. |
| R3 | Segment ordinal range and timestamp order. |
| R4 | Human-curated `speaker_statement` requires a known speaker; reject, not needs-review. |
| R5 | Bounded multi-clause/coupling-marker atomicity heuristic. |
| R6 | `speaker_reasoning` edge requires transcript version + exact quote. |
| R7 | A supplied canonical concept must have a `concept_source`; proposed concepts are allowed without automatic promotion. |
| R8 | `macro_bridge` evaluation needs external evidence, including publisher, content SHA, and observed period. |
| R9 | Forecast requires nonempty outcome condition plus at least one time-window bound. |
| R10 | Model output cannot emit `speaker_statement`, even when speaker is known. |

**R4/R10 separation (audit F-4):** R4 validates legitimate human-curated
speaker statements. R10 is the stricter model-output boundary, so a model
claim is rejected before it can become an authoritative speaker statement.

### 3.4 Runner, status, and CLI

| File | Change |
|---|---|
| `lib/houchen_runner.py` | `run_analyze`, `run_validate`, `run_concept_seed`; correct CTE analysis scope; successful/failed validate attempts; formal-row materialization and idempotency per analysis run. |
| `lib/houchen_status.py` | `claims`, `concepts`, and `analyze_scope` status buckets; coverage `claim_outcomes`, `concept_state`, and deduplicated CTE scope counts. |
| `scripts/houchen_pipeline.py` | `analyze`, `validate`, `concept-seed`, `--provider`, `--model`, all with zero-write dry-run paths and existing exit-code policy. |
| `scripts/test_houchen_pipeline.py` | Dry-run zero-write tests, bucket shape tests, concept-seed idempotency, provider guard, and full offline PR-3 CLI E2E. |

The analysis scope CTE explicitly deduplicates historical successful attempts
and requires that the parent analysis run succeeded. It does not suppress a
retry because of a partial/failed prior run.

### 3.5 Concept semantics

- Domain skeleton (F-1): `political_economy`, `state_governance`,
  `society_psychology`, `international_order`, `technology_ai`,
  `history_interpretation`, `method_media`.
- Domain seeds are idempotent and never overwrite a curated nonempty name.
- Model-proposed concepts always remain `proposed`.
- A concept link to an unknown concept makes it a reversible proposed concept;
  it does not assert canonical status.
- `concept_source` is written only when its quote passes the same R2 quote
  comparison gate.

---

## 4. End-to-end offline proof

`test_cli_pr3_offline_full_chain_materializes_all_rows` executes:

```text
catalog (canonical fake yt-dlp)
→ fetch-captions
→ normalize
→ concept-seed
→ analyze --provider fake
→ analyze --no-pending --provider anthropic  # controlled failure, no network
→ validate
→ validate again                              # formal-row idempotency
```

It asserts all of the following in a temporary `houchen.sqlite3` database:

- 1 accepted claim;
- at least 2 rejected claims (the fixture's intentional R2 and R5 cases);
- 1 claim source;
- proposed concepts and at least one concept source;
- 1 claim-concept link;
- 1 evidence mention;
- 1 forecast;
- second `validate` creates no extra claim rows;
- real-provider CLI selection returns controlled `analyze_failed` / exit 3
  without network activity.

---

## 5. Verification evidence

Executed from `/Users/kjonekong/macro-pipeline` after the final fixes:

```text
$ python3 -m pytest scripts/test_houchen_validator.py \
    scripts/test_houchen_analyzer.py scripts/test_houchen_pipeline.py -q
74 passed in 3.99s

$ python3 -m pytest scripts/test_houchen_*.py \
    scripts/test_ledger.py scripts/test_migrations.py -q
196 passed in 8.58s

$ python3 -m pytest scripts -q
314 passed in 9.82s

$ python3 -m py_compile lib/houchen_*.py scripts/houchen_pipeline.py
exit 0

$ <temporary-root> analyze --dry-run
$ <temporary-root> validate --dry-run
$ <temporary-root> concept-seed --dry-run
COMPILE_AND_DRY_RUN_ZERO_WRITE_OK
```

The first combined compile/dry-run shell assertion incorrectly expected the
fresh temporary *directory itself* not to exist (exit 1 after all three CLI
commands printed successful dry-run JSON). The corrected check asserted no
children exist in the directory and passed; no code change was required.

---

## 6. Out of scope / explicitly not authorized

- Real-model evaluation or use of any API key; `config/houchen_analyze.env`
  remains only a namespace reservation and no secret file was created
  (audit F-6).
- FTS5/full-text search (PR-4).
- Obsidian publishing (PR-5).
- Macro bridge / external-evidence ingestion (PR-6).
- Automated forecast hit/failure adjudication.
- Automatic concept promotion/merging.
- Live full-channel analysis, media downloads, deploys, schedules, commits,
  or pushes.

---

## 7. Reviewer acceptance checklist

### Required functional review

- [ ] Verify `schema_version` migrates an empty corpus DB through v1 → v2 →
      v3, with all 13 v3 tables and exact constraints.
- [ ] Review the ten hard-validator rules in `lib/houchen_validator.py` and
      their positive/negative tests in `scripts/test_houchen_validator.py`.
- [ ] Confirm `speaker_statement` from model output is rejected rather than
      silently relabeled.
- [ ] Confirm the multi-video analysis artifact cannot overwrite a prior
      video's item.
- [ ] Confirm a revalidated analysis run does not duplicate formal rows.
- [ ] Confirm `concept.status` stays `proposed` absent explicit human
      promotion plus source.
- [ ] Confirm `analyze --provider anthropic` remains fail-closed and offline.

### Required isolation review

- [ ] Verify the five protected SHA-256 values in §8.
- [ ] Verify `data/store.db` SHA remains the accepted baseline.
- [ ] Verify `find data/houchen -type f` returns `0`.
- [ ] Confirm the PR-3 macro-isolation E2E path remains in the full suite
      (audit F-5).

### Gate decision

**PR-3 ACCEPTED (Cursor 2026-08-24).** The independent Cursor acceptance is
recorded in `reviews/PR3_ACCEPTANCE_CURSOR_2026-08-24.md`; its second
verification reproduced 74 / 196 / 314 passed and confirmed the red-line
baseline. This document is now locked as the local delivery evidence.

Commit is authorized by the user. Push, deploy, schedules, and real-model
analysis remain explicitly out of scope.

**Local `/review` tool note:** the repository checkout reported `main` as the
current branch and has no resolvable `origin/main`; the branch-based gstack
review correctly stopped before diffing instead of manufacturing a PR verdict.
This is not evidence of a clean independent review. The accepted Cursor review
above is the applicable independent acceptance evidence.

---

## 8. Protected artifact SHA-256 verification (final)

```text
5b1ec4840c0845d966fdf3d8f7807c8fe30547b819960169ca150b16b2f69594  docs/厚辰/不明白访谈厚辰.docx
c5840da93b3095ce23c303421e4d08c922960c2a68bd50fed4f29df4f9c2749a  docs/厚辰/重庆上街-厚辰.docx
0146a3127e424c8a4030ed82a06051996224d8a3cfaddc36fd9cd2b7623dba3e  docs/厚辰/世界苦茶研究库/CLAUDE_CODE_IMPLEMENTATION_BRIEF.md
8c5b1ac447d7372181b24399416ec95296f628649669b52e6092abf68e359607  docs/厚辰/世界苦茶研究库/CODEX_ACCEPTANCE_PROTOCOL.md
ef33767542806bed75c2d32a661869d623a8d3a52fc68413eeaeef0e07a6c412  docs/厚辰/世界苦茶研究库/ENGINEERING_TEST_PLAN.md
52c12c82d11f32c05ae6658aade5e20da1c1204966d386c2e05be516a5898ed7  data/store.db
```

```text
$ find data/houchen -type f | wc -l
0
```
