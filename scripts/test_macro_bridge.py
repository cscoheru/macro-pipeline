"""Tests for PR-5 macro bridge module.

Covers:
  - Safety: store.db readonly, SHA unchanged after scan
  - Functional: keyword matching, relation assessment
  - Integration: scan against real houchen DB, JSONL export
"""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import macro_bridge  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def houchen_conn():
    """In-memory houchen DB with minimal schema."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    # Minimal schema for testing
    c.executescript("""
        CREATE TABLE claim (
            claim_id TEXT PRIMARY KEY,
            video_id TEXT NOT NULL,
            claim_text TEXT NOT NULL,
            claim_type TEXT NOT NULL,
            speaker TEXT,
            layer TEXT NOT NULL,
            temporal_scope TEXT,
            modality TEXT,
            status TEXT NOT NULL,
            analysis_run_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE evaluation (
            evaluation_id TEXT PRIMARY KEY,
            target_kind TEXT NOT NULL,
            target_id TEXT NOT NULL,
            evaluator TEXT NOT NULL,
            as_of TEXT,
            verdict TEXT,
            reasoning TEXT,
            status TEXT,
            external_evidence_id TEXT,
            created_at TEXT NOT NULL
        );
    """)
    # Ensure macro_link_candidate table
    macro_bridge._ensure_table(c)
    yield c
    c.close()


@pytest.fixture
def macro_conn():
    """In-memory macro store with test observations."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("""
        CREATE TABLE observations (
            source TEXT NOT NULL,
            series TEXT NOT NULL,
            date TEXT NOT NULL,
            value REAL,
            PRIMARY KEY (source, series, date)
        )
    """)
    # Insert test observations
    c.executemany("INSERT INTO observations VALUES (?,?,?,?)", [
        ("fred", "CPIAUCSL", "2026-07-01", 332.813),
        ("fred", "UNRATE", "2026-07-01", 4.1),
        ("fred", "FEDFUNDS", "2026-07-01", 3.63),
        ("fred", "GDPC1", "2026-04-01", 24270.599),
        ("cn_stats_cpi", "cpi_yoy_yoy", "2026-07", 0.5),
        ("cn_pbc", "pbc_m2_yoy", "2026-07", 7.0),
        ("cn_stats_pmi", "pmi_mfg", "2026-07", 49.4),
        ("cn_mof", "mof_revenue_yoy", "2026-07", -2.6),
    ])
    c.commit()
    yield c
    c.close()


@pytest.fixture
def sample_keywords():
    """Minimal keyword mapping for testing."""
    return {
        "CPI": ["fred:CPIAUCSL", "cn_stats_cpi:cpi_yoy_yoy"],
        "通胀": ["fred:CPIAUCSL", "cn_stats_cpi:cpi_yoy_yoy"],
        "失业": ["fred:UNRATE"],
        "利率": ["fred:FEDFUNDS"],
        "PMI": ["cn_stats_pmi:pmi_mfg"],
        "贸易战": [],
    }


@pytest.fixture
def sample_observations(macro_conn):
    return macro_bridge.fetch_latest_observations(macro_conn)


def _insert_claim(conn, claim_id="clm_test001", text="中国CPI持续走低",
                  claim_type="descriptive", status="accepted"):
    conn.execute(
        "INSERT INTO claim VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (claim_id, "abcdefghijk", text, claim_type, None,
         "speaker_statement", None, None, status, "hcrun_test", "2026-01-01T00:00:00Z")
    )


# ---------------------------------------------------------------------------
# 1. Safety tests
# ---------------------------------------------------------------------------

class TestSafety:
    """store.db must never be written to."""

    def test_readonly_connection_rejects_writes(self, tmp_path):
        """Opening store.db with mode=ro should reject INSERT."""
        # Create a temp DB to test with
        db = tmp_path / "test.db"
        c = sqlite3.connect(str(db))
        c.execute("CREATE TABLE t (x TEXT)")
        c.execute("INSERT INTO t VALUES ('a')")
        c.commit()
        c.close()

        # Open readonly
        ro_conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        ro_conn.execute("PRAGMA query_only = ON")
        with pytest.raises(sqlite3.OperationalError):
            ro_conn.execute("INSERT INTO t VALUES ('b')")
        ro_conn.close()

    def test_verify_store_sha_correct(self):
        """verify_store_sha returns True for actual SHA."""
        store_path = PROJECT_ROOT / "data" / "store.db"
        if not store_path.exists():
            pytest.skip("store.db not present")
        # Compute actual SHA
        import hashlib
        h = hashlib.sha256()
        with open(store_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        actual = h.hexdigest()
        assert macro_bridge.verify_store_sha(actual, store_path) is True

    def test_verify_store_sha_wrong(self):
        """verify_store_sha returns False for wrong SHA."""
        store_path = PROJECT_ROOT / "data" / "store.db"
        if not store_path.exists():
            pytest.skip("store.db not present")
        assert macro_bridge.verify_store_sha("0" * 64, store_path) is False

    def test_macro_store_readonly(self):
        """open_macro_store_readonly should reject writes."""
        store_path = PROJECT_ROOT / "data" / "store.db"
        if not store_path.exists():
            pytest.skip("store.db not present")
        conn = macro_bridge.open_macro_store_readonly(store_path)
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO observations VALUES ('x','y','z',1.0)")
        conn.close()

    def test_store_sha_unchanged_after_scan(self):
        """Full scan against real DBs must not change store.db SHA."""
        store_path = PROJECT_ROOT / "data" / "store.db"
        houchen_path = PROJECT_ROOT / "data" / "houchen" / "houchen.sqlite3"
        if not store_path.exists() or not houchen_path.exists():
            pytest.skip("DBs not present")

        import hashlib
        h = hashlib.sha256()
        with open(store_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        sha_before = h.hexdigest()

        # Run scan
        macro_conn = macro_bridge.open_macro_store_readonly(store_path)
        houchen_conn = sqlite3.connect(str(houchen_path))
        houchen_conn.row_factory = sqlite3.Row
        try:
            macro_bridge.scan_all(houchen_conn, macro_conn)
        finally:
            macro_conn.close()
            houchen_conn.close()

        h2 = hashlib.sha256()
        with open(store_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h2.update(chunk)
        sha_after = h2.hexdigest()
        assert sha_before == sha_after, "store.db SHA changed after scan!"


# ---------------------------------------------------------------------------
# 2. Functional tests
# ---------------------------------------------------------------------------

class TestKeywordMatching:
    def test_match_cpi_keyword(self, sample_keywords):
        result = macro_bridge._match_keywords("中国CPI数据公布", sample_keywords)
        assert "fred:CPIAUCSL" in result
        assert "cn_stats_cpi:cpi_yoy_yoy" in result

    def test_match_chinese_keyword(self, sample_keywords):
        result = macro_bridge._match_keywords("通胀率持续上升", sample_keywords)
        assert "fred:CPIAUCSL" in result

    def test_no_match(self, sample_keywords):
        result = macro_bridge._match_keywords("今天的天气很好", sample_keywords)
        assert result == []

    def test_empty_series_list(self, sample_keywords):
        """Keywords with empty series list should produce empty match."""
        result = macro_bridge._match_keywords("贸易战升级", sample_keywords)
        assert result == []

    def test_dedup_preserves_order(self, sample_keywords):
        result = macro_bridge._match_keywords("CPI和通胀同时提及", sample_keywords)
        # Should not duplicate fred:CPIAUCSL
        assert result.count("fred:CPIAUCSL") == 1


class TestRelationAssessment:
    def test_no_observation_returns_unresolved(self):
        rel, conf, reason = macro_bridge._assess_relation(
            "CPI走高", "descriptive", "fred:CPIAUCSL", None
        )
        assert rel == "unresolved"
        assert conf == "low"

    def test_descriptive_claim_returns_contextualizes(self, sample_observations):
        obs = sample_observations.get("fred:CPIAUCSL")
        rel, conf, _ = macro_bridge._assess_relation(
            "CPI数据", "descriptive", "fred:CPIAUCSL", obs
        )
        assert rel == "contextualizes"
        assert conf == "medium"

    def test_predictive_claim_returns_unresolved_v1(self, sample_observations):
        """V1 doesn't do trend analysis; predictive → unresolved."""
        obs = sample_observations.get("fred:CPIAUCSL")
        rel, conf, _ = macro_bridge._assess_relation(
            "CPI将继续上升", "predictive", "fred:CPIAUCSL", obs
        )
        assert rel == "unresolved"

    def test_empty_macro_key_contextualizes(self):
        rel, _, _ = macro_bridge._assess_relation(
            "贸易战加剧", "descriptive", "",
            {"source": "", "series": "", "date": "", "value": None}
        )
        assert rel == "contextualizes"


class TestFindCandidates:
    def test_finds_candidates_for_cpi_claim(
        self, sample_keywords, sample_observations
    ):
        candidates = macro_bridge.find_candidates(
            claim_id="clm_test001",
            claim_text="中国CPI同比上涨0.5%",
            claim_type="descriptive",
            keywords=sample_keywords,
            observations=sample_observations,
        )
        assert len(candidates) >= 1
        assert all(c.claim_id == "clm_test001" for c in candidates)
        sources = {c.macro_source for c in candidates}
        assert "fred" in sources or "cn_stats_cpi" in sources

    def test_no_candidates_for_unrelated_claim(
        self, sample_keywords, sample_observations
    ):
        candidates = macro_bridge.find_candidates(
            claim_id="clm_test002",
            claim_text="今天天气很好",
            claim_type="descriptive",
            keywords=sample_keywords,
            observations=sample_observations,
        )
        assert candidates == []

    def test_candidate_has_valid_id(self, sample_keywords, sample_observations):
        candidates = macro_bridge.find_candidates(
            claim_id="clm_test003",
            claim_text="PMI跌破荣枯线",
            claim_type="descriptive",
            keywords=sample_keywords,
            observations=sample_observations,
        )
        assert len(candidates) == 1
        assert candidates[0].candidate_id.startswith("mlc_")

    def test_candidate_to_dict(self, sample_keywords, sample_observations):
        candidates = macro_bridge.find_candidates(
            claim_id="clm_test004",
            claim_text="美联储利率决议",
            claim_type="descriptive",
            keywords=sample_keywords,
            observations=sample_observations,
        )
        assert len(candidates) >= 1
        d = candidates[0].to_dict()
        assert "candidate_id" in d
        assert "relation" in d
        assert d["method"] == "keyword_match"


class TestFetchObservations:
    def test_fetches_latest_per_series(self, macro_conn):
        obs = macro_bridge.fetch_latest_observations(macro_conn)
        assert "fred:CPIAUCSL" in obs
        assert obs["fred:CPIAUCSL"]["value"] == 332.813
        assert obs["fred:UNRATE"]["value"] == 4.1

    def test_returns_all_series(self, macro_conn):
        obs = macro_bridge.fetch_latest_observations(macro_conn)
        assert len(obs) == 8  # 8 unique source:series pairs


class TestLoadKeywords:
    def test_loads_real_config(self):
        keywords = macro_bridge.load_keywords()
        assert isinstance(keywords, dict)
        assert "CPI" in keywords or "通胀" in keywords

    def test_returns_empty_for_missing_file(self, tmp_path):
        keywords = macro_bridge.load_keywords(tmp_path / "nonexistent.yaml")
        assert keywords == {}


# ---------------------------------------------------------------------------
# 3. Integration tests
# ---------------------------------------------------------------------------

class TestScanAndExport:
    def test_scan_writes_candidates(self, houchen_conn, macro_conn, sample_keywords):
        _insert_claim(houchen_conn, text="中国CPI同比走低")
        _insert_claim(houchen_conn, claim_id="clm_test002", text="美联储加息")

        keywords = sample_keywords
        observations = macro_bridge.fetch_latest_observations(macro_conn)

        # Monkeypatch load_keywords to use test keywords
        original_load = macro_bridge.load_keywords
        macro_bridge.load_keywords = lambda path=None: keywords
        try:
            candidates = macro_bridge.scan_all(houchen_conn, macro_conn)
        finally:
            macro_bridge.load_keywords = original_load

        assert len(candidates) >= 2

        # Verify written to DB
        rows = houchen_conn.execute(
            "SELECT COUNT(*) as cnt FROM macro_link_candidate"
        ).fetchone()
        assert rows["cnt"] == len(candidates)

    def test_export_jsonl(self, houchen_conn, tmp_path):
        # Insert claim first (FK requirement)
        _insert_claim(houchen_conn, claim_id="clm_test001", text="CPI data")
        # Insert a test candidate
        from datetime import datetime, timezone
        houchen_conn.execute(
            """INSERT INTO macro_link_candidate
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            ("mlc_test001", "clm_test001", "fred", "CPIAUCSL",
             "2026-07-01", 332.813, "contextualizes", "medium",
             "test reasoning", datetime.now(timezone.utc).isoformat(),
             "keyword_match", 0)
        )
        houchen_conn.commit()

        output = tmp_path / "test_export.jsonl"
        count = macro_bridge.export_jsonl(houchen_conn, output)
        assert count == 1
        assert output.exists()

        # Verify JSONL content
        with open(output) as f:
            line = json.loads(f.readline())
        assert line["candidate_id"] == "mlc_test001"
        assert line["macro_source"] == "fred"
        assert line["relation"] == "contextualizes"

    def test_import_to_evaluation(self, houchen_conn):
        candidate = macro_bridge.MacroLinkCandidate(
            candidate_id="mlc_test001",
            claim_id="clm_test001",
            macro_source="fred",
            macro_series="CPIAUCSL",
            macro_period="2026-07-01",
            macro_value=332.813,
            relation="supports",
            confidence="medium",
            reasoning="test",
        )
        eval_id = macro_bridge.import_to_evaluation(candidate, houchen_conn)
        assert eval_id.startswith("evl_")

        row = houchen_conn.execute(
            "SELECT * FROM evaluation WHERE evaluation_id=?", (eval_id,)
        ).fetchone()
        assert row is not None
        assert row["target_kind"] == "claim"
        assert row["target_id"] == "clm_test001"
        assert row["evaluator"] == "macro_bridge"
        assert row["verdict"] == "confirmed"  # supports → confirmed


class TestEnsureTable:
    def test_creates_table(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        macro_bridge._ensure_table(c)
        # Verify table exists
        row = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='macro_link_candidate'"
        ).fetchone()
        assert row is not None
        c.close()

    def test_idempotent(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        macro_bridge._ensure_table(c)
        macro_bridge._ensure_table(c)  # Should not raise
        c.close()

    def test_check_constraint_relation(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        macro_bridge._ensure_table(c)
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(
                """INSERT INTO macro_link_candidate
                   VALUES ('mlc_bad','clm_x','fred','X','2026',1.0,
                           'INVALID','high','test','2026-01-01','keyword_match',0)"""
            )
        c.close()
