"""PR-4 Phase 0 — FTS5 search tests (brief §10).

The tests cover:

  1. Schema v4 brings the FTS5 substrate online (transcript_fts,
     claim_fts, concept_fts, concept_alias_fts) and the 12 sync
     triggers.
  2. Each `transcript_segment` insert / update / delete propagates to
     `transcript_fts` (and the same for the other three FTS tables).
  3. `claim_fts` only contains `accepted` rows; a `needs_review` row
     is invisible to MATCH.
  4. The fixed query set from
     `scripts/houchen_fixtures/fixed_query_set.py` returns at least
     `min_hits` rows on the canonical fixture for every entry.
  5. The houchen_search module's read-only contract:
     `search_transcript` / `search_claim` / `search_concept` /
     `search_concept_alias` never write to any FTS table.
  6. Validation guards (empty / unbalanced-quote / non-string query).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.dirname(__file__))

import houchen_migrations  # noqa: E402
import houchen_schema  # noqa: E402
import houchen_search  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "houchen_fixtures"))
from fixed_query_set import FIXED_QUERY_SET  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_minimal_corpus(c: sqlite3.Connection) -> None:
    """Insert the minimum number of rows for the fixed query set to
    pass. Each row is crafted to MATCH a specific query in the
    fixed set; see the table at the top of the function."""
    now = _now()
    # One video
    c.execute(
        "INSERT INTO video(video_id, discovered_at, last_seen_at,"
        " availability, content_kind, metadata_sha256)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        ("aaaaaaaaaaa", now, now, "public", "video", "a" * 64))
    # One raw_caption
    c.execute(
        "INSERT INTO raw_caption(video_id, language, caption_kind, format,"
        " content_sha256, local_path, byte_count, cue_count, fetched_at,"
        " yt_dlp_version, source_metadata_sha256)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("aaaaaaaaaaa", "zh-Hans", "manual", "vtt", "b" * 64, "/x", 1, 1, now,
         "yt", "c" * 64))
    # corpus_run required for claim.analysis_run_id FK.
    c.execute(
        "INSERT INTO corpus_run(run_id, kind, started_at, finished_at, status,"
        " config_sha256, tool_versions_json)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("hcrun_test", "analyze", now, now, "success", "z" * 64, "{}"))
    # One transcript_version
    c.execute(
        "INSERT INTO transcript_version(transcript_version_id, video_id,"
        " raw_caption_sha256, normalizer_name, normalizer_version,"
        " status, content_sha256, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("hctv_test", "aaaaaaaaaaa", "b" * 64, "n", "v", "ok", "d" * 64, now))
    # transcript_segments
    segments = [
        (0,    0, 1000, "中央财政转移支付"),
        (1, 1000, 2000, "地方政府债务水平"),
        (2, 2000, 3000, "中央与地方公共服务"),
        (3, 3000, 4000, "基础设施投资"),
    ]
    c.executemany(
        "INSERT INTO transcript_segment(transcript_version_id, ordinal,"
        " start_ms, end_ms, text, raw_cue_start, raw_cue_end)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [("hctv_test", o, s, e, t, s, e) for (o, s, e, t) in segments])
    # claim rows
    c.execute(
        "INSERT INTO claim(claim_id, video_id, claim_text, claim_type, layer,"
        " status, analysis_run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("hccl_a", "aaaaaaaaaaa", "中央财政扩张的逻辑", "normative",
         "speaker_reasoning", "accepted", "hcrun_test", now))
    c.execute(
        "INSERT INTO claim(claim_id, video_id, claim_text, claim_type, layer,"
        " status, analysis_run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("hccl_b", "aaaaaaaaaaa", "基础设施投资应增加", "normative",
         "system_evaluation", "accepted", "hcrun_test", now))
    c.execute(
        "INSERT INTO claim(claim_id, video_id, claim_text, claim_type, layer,"
        " status, analysis_run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("hccl_nr", "aaaaaaaaaaa", "这是一条尚未接受的主张", "descriptive",
         "speaker_statement", "needs_review", "hcrun_test", now))
    # concept rows
    c.execute(
        "INSERT INTO concept(concept_id, canonical_name, definition, status,"
        " origin, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("hccon_w", "财政转移支付", "中央对地方的转移支付制度。",
         "canonical", "human", now, now))
    c.execute(
        "INSERT INTO concept(concept_id, canonical_name, definition, status,"
        " origin, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("hccon_p", "权力下放", "中央向地方分权的过程。",
         "proposed", "corpus", now, now))
    # concept_alias rows
    c.execute(
        "INSERT INTO concept_alias(alias_id, concept_id, alias, source,"
        " created_at) VALUES (?, ?, ?, ?, ?)",
        ("hcali_1", "hccon_w", "转移支付", "human", now))
    c.execute(
        "INSERT INTO concept_alias(alias_id, concept_id, alias, source,"
        " created_at) VALUES (?, ?, ?, ?, ?)",
        ("hcali_2", "hccon_p", "央地分权", "human", now))
    c.commit()


def _fresh_v4_db() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    houchen_migrations.ensure_schema(c)
    _seed_minimal_corpus(c)
    return c


# ---------------------------------------------------------------------------
# 1. Schema v4 brings the FTS5 substrate online
# ---------------------------------------------------------------------------

class TestV4Fts5Substrate(unittest.TestCase):
    def test_all_four_fts_tables_exist(self):
        c = _fresh_v4_db()
        names = {r[0] for r in c.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type='table' AND name LIKE '%_fts'")}
        self.assertEqual(
            names,
            {"transcript_fts", "claim_fts", "concept_fts", "concept_alias_fts"})
        c.close()

    def test_all_twelve_sync_triggers_exist(self):
        c = _fresh_v4_db()
        rows = c.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
            " AND name LIKE 'trg_%' ORDER BY name").fetchall()
        names = {r[0] for r in rows}
        expected = {
            "trg_transcript_segment_ai", "trg_transcript_segment_au",
            "trg_transcript_segment_ad",
            "trg_claim_ai", "trg_claim_au", "trg_claim_ad",
            "trg_concept_ai", "trg_concept_au", "trg_concept_ad",
            "trg_concept_alias_ai", "trg_concept_alias_au", "trg_concept_alias_ad",
        }
        self.assertEqual(expected.issubset(names), True,
                         f"missing: {expected - names}")
        c.close()

    def test_validate_schema_passes_on_v4(self):
        c = _fresh_v4_db()
        self.assertTrue(houchen_schema.validate_schema(c))
        c.close()

    def test_fts5_installed_helper(self):
        c = _fresh_v4_db()
        self.assertTrue(houchen_search.fts5_installed(c))
        c.close()


# ---------------------------------------------------------------------------
# 2. Trigger propagation
# ---------------------------------------------------------------------------

class TestTriggersPropagateInsertsUpdatesDeletes(unittest.TestCase):
    def test_transcript_segment_insert_populates_fts(self):
        c = _fresh_v4_db()
        n_before = c.execute("SELECT COUNT(*) FROM transcript_fts").fetchone()[0]
        c.execute(
            "INSERT INTO transcript_segment(transcript_version_id, ordinal,"
            " start_ms, end_ms, text, raw_cue_start, raw_cue_end)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("hctv_test", 99, 99000, 100000, "新增段落", 99000, 100000))
        c.commit()
        n_after = c.execute("SELECT COUNT(*) FROM transcript_fts").fetchone()[0]
        self.assertEqual(n_after, n_before + 1)
        hit = c.execute("SELECT text FROM transcript_fts WHERE text='新增段落'").fetchall()
        self.assertEqual(len(hit), 1)
        c.close()

    def test_transcript_segment_update_propagates_to_fts(self):
        c = _fresh_v4_db()
        c.execute(
            "UPDATE transcript_segment SET text='改写后的中央财政'"
            " WHERE transcript_version_id='hctv_test' AND ordinal=0")
        c.commit()
        hit = c.execute(
            "SELECT text FROM transcript_fts WHERE text='改写后的中央财政'"
        ).fetchall()
        self.assertEqual(len(hit), 1)
        c.close()

    def test_transcript_segment_delete_removes_from_fts(self):
        c = _fresh_v4_db()
        n_before = c.execute("SELECT COUNT(*) FROM transcript_fts").fetchone()[0]
        c.execute(
            "DELETE FROM transcript_segment"
            " WHERE transcript_version_id='hctv_test' AND ordinal=0")
        c.commit()
        n_after = c.execute("SELECT COUNT(*) FROM transcript_fts").fetchone()[0]
        self.assertEqual(n_after, n_before - 1)
        hit = c.execute(
            "SELECT text FROM transcript_fts WHERE text='中央财政转移支付'").fetchall()
        self.assertEqual(len(hit), 0)
        c.close()

    def test_claim_fts_only_contains_accepted(self):
        c = _fresh_v4_db()
        n = c.execute("SELECT COUNT(*) FROM claim_fts").fetchone()[0]
        # Two accepted rows were seeded; the needs_review row is excluded.
        self.assertEqual(n, 2)
        # The needs_review text has 8 characters; trigram-match on a
        # 3-char substring of it confirms it is NOT in the FTS index.
        hit = c.execute(
            "SELECT claim_text FROM claim_fts"
            " WHERE claim_fts MATCH '尚未接受'").fetchall()
        self.assertEqual(len(hit), 0)
        c.close()

    def test_claim_status_flip_moves_fts_row(self):
        c = _fresh_v4_db()
        # Flip needs_review → accepted, then ensure the row is in the FTS.
        c.execute(
            "UPDATE claim SET status='accepted'"
            " WHERE claim_id='hccl_nr'")
        c.commit()
        hit = c.execute(
            "SELECT claim_text FROM claim_fts"
            " WHERE claim_fts MATCH '尚未接受'").fetchall()
        self.assertEqual(len(hit), 1)
        c.close()

    def test_concept_status_filter(self):
        c = _fresh_v4_db()
        # Both proposed and canonical concepts are indexed; deprecated
        # is not. We don't have a deprecated row in the seed fixture, so
        # the assertion is just that both seeded concepts are in the
        # FTS table. trigram tokenizer needs ≥3 chars per token.
        rows = c.execute(
            "SELECT canonical_name FROM concept_fts"
            " WHERE concept_fts MATCH '财政转移 OR 权力下放'").fetchall()
        self.assertEqual(len(rows), 2)
        c.close()


# ---------------------------------------------------------------------------
# 3. The fixed query set
# ---------------------------------------------------------------------------

class TestFixedQuerySet(unittest.TestCase):
    def test_every_query_yields_at_least_min_hits(self):
        c = _fresh_v4_db()
        for kind, query, min_hits, label in FIXED_QUERY_SET:
            result = houchen_search.search(conn=c, kind=kind, query=query,
                                            limit=50)
            n = (len(result.transcripts) + len(result.claims)
                 + len(result.concepts) + len(result.aliases))
            self.assertGreaterEqual(
                n, min_hits,
                f"query {label!r} (kind={kind}, q={query!r}) returned"
                f" {n} hits, expected ≥ {min_hits}")
        c.close()


# ---------------------------------------------------------------------------
# 4. houchen_search module: read-only contract + helpers
# ---------------------------------------------------------------------------

class TestSearchModuleContract(unittest.TestCase):
    def setUp(self):
        self.c = _fresh_v4_db()

    def tearDown(self):
        self.c.close()

    def test_search_transcript_resolves_video_id_via_join(self):
        hits = houchen_search.search_transcript(self.c, "中央财政", limit=10)
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0].video_id, "aaaaaaaaaaa")
        self.assertEqual(hits[0].transcript_version_id, "hctv_test")

    def test_search_claim_returns_accepted_only(self):
        hits = houchen_search.search_claim(self.c, "财政扩张", limit=10)
        # The needs_review row is not in the FTS; this query only hits
        # the normative accepted row.
        self.assertGreaterEqual(len(hits), 1)
        for h in hits:
            self.assertNotEqual(h.claim_id, "hccl_nr")

    def test_search_concept_matches_canonical_name(self):
        hits = houchen_search.search_concept(self.c, "财政转移", limit=10)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].canonical_name, "财政转移支付")

    def test_search_concept_alias_matches_aliases(self):
        hits = houchen_search.search_concept_alias(self.c, "转移支付", limit=10)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].concept_id, "hccon_w")

    def test_search_all_returns_combined_result(self):
        result = houchen_search.search(conn=self.c, kind="all",
                                       query="中央财政", limit=20)
        self.assertGreater(result.total, 0)
        self.assertGreater(len(result.transcripts) + len(result.concepts), 0)

    def test_query_empty_raises(self):
        with self.assertRaises(ValueError):
            houchen_search.search(self.c, kind="claim", query="   ")

    def test_query_unbalanced_quote_raises(self):
        with self.assertRaises(ValueError):
            houchen_search.search(self.c, kind="claim",
                                  query='unbalanced "quote')

    def test_query_non_string_raises(self):
        with self.assertRaises(TypeError):
            houchen_search.search(self.c, kind="claim", query=123)

    def test_invalid_kind_raises(self):
        with self.assertRaises(ValueError):
            houchen_search.search(self.c, kind="bogus", query="x")

    def test_search_never_writes_to_fts(self):
        n_before_t = self.c.execute(
            "SELECT COUNT(*) FROM transcript_fts").fetchone()[0]
        n_before_c = self.c.execute(
            "SELECT COUNT(*) FROM claim_fts").fetchone()[0]
        houchen_search.search(self.c, kind="all", query="中央财政", limit=20)
        n_after_t = self.c.execute(
            "SELECT COUNT(*) FROM transcript_fts").fetchone()[0]
        n_after_c = self.c.execute(
            "SELECT COUNT(*) FROM claim_fts").fetchone()[0]
        self.assertEqual(n_before_t, n_after_t)
        self.assertEqual(n_before_c, n_after_c)


# ---------------------------------------------------------------------------
# 5. CLI surface
# ---------------------------------------------------------------------------

class TestSearchCLISurface(unittest.TestCase):
    """The CLI must accept `--kind`, `--query`, `--limit` and a read-only
    subcommand that does not write the corpus. We invoke the CLI module
    directly (not via subprocess) for speed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["HOUCHEN_DATA_ROOT"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("HOUCHEN_DATA_ROOT", None)
        self.tmp.cleanup()

    def _seed_root(self):
        # Write a v4 DB into the tmp root.
        from scripts import houchen_pipeline  # noqa: F401  (sys.path side effect)
        # Reuse ensure_schema + fixture; we need a writable houchen.sqlite3.
        c = sqlite3.connect(os.path.join(self.tmp.name, "houchen.sqlite3"))
        c.execute("PRAGMA foreign_keys=ON")
        houchen_migrations.ensure_schema(c)
        _seed_minimal_corpus(c)
        c.close()

    def test_dry_run_zero_writes(self):
        self._seed_root()
        before = set()
        for r, _, files in os.walk(self.tmp.name):
            for f in files:
                before.add(os.path.join(r, f))
        from scripts import houchen_pipeline
        rc = houchen_pipeline.main([
            "search", "--kind", "transcript", "--query", "中央财政", "--dry-run",
        ])
        self.assertEqual(rc, 0)
        after = set()
        for r, _, files in os.walk(self.tmp.name):
            for f in files:
                after.add(os.path.join(r, f))
        self.assertEqual(before, after)

    def test_search_returns_json_with_total(self):
        self._seed_root()
        from scripts import houchen_pipeline
        # Capture stdout via redirect
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = houchen_pipeline.main([
                "search", "--kind", "all", "--query", "中央财政", "--limit", "5",
            ])
        self.assertEqual(rc, 0)
        import json
        out = json.loads(buf.getvalue())
        self.assertEqual(out["kind"], "all")
        self.assertEqual(out["query"], "中央财政")
        self.assertGreater(out["total"], 0)


if __name__ == "__main__":
    unittest.main()
