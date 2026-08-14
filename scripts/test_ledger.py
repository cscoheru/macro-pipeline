"""Phase 1 judgement ledger - pytest suite.

Runs entirely against an in-memory SQLite DB (fresh schema per test); never
touches the real data/store.db. seed_phase1 reads the real snapshot files on
disk (to hash real content) but writes into the in-memory conn.

Run:  python3 -m pytest scripts/test_ledger.py -v
"""
import os
import sys
import sqlite3

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import ledger
import paths


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    """Fresh in-memory ledger: schema + triggers, FK on."""
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=5000")
    ledger.init_schema(c)
    yield c
    c.close()


def _sha64():
    return "a" * 64


# ---------------------------------------------------------------------------
# IDs
# ---------------------------------------------------------------------------

def test_new_id_prefix_and_uniqueness():
    ids = [ledger.new_id("claim") for _ in range(200)]
    assert all(i.startswith("clm_") for i in ids)
    assert all(len(i) == 4 + 32 for i in ids)  # prefix_ + uuid7 hex
    assert len(set(ids)) == len(ids)           # unique
    # other entities carry their own prefix
    assert ledger.new_id("evidence_snapshot").startswith("evi_")
    assert ledger.new_id("ledger_event").startswith("evt_")


# ---------------------------------------------------------------------------
# Event primitives + state derivation
# ---------------------------------------------------------------------------

def test_append_event_writes_all_fields(conn):
    clm = ledger.create_claim(conn, statement="payload test")
    ledger.append_event(conn, "claim", clm, "active", "alice", "reviewed",
                        from_status="draft", payload={"k": 1})
    row = conn.execute(
        "SELECT entity_type, entity_id, from_status, to_status, actor, reason,"
        " payload_sha256 FROM ledger_event WHERE entity_id=?"
        " ORDER BY occurred_at DESC, evt_id DESC LIMIT 1", (clm,)).fetchone()
    assert row[0] == "claim"
    assert row[2] == "draft" and row[3] == "active"
    assert row[4] == "alice"
    assert row[6] is not None   # payload hashed


def test_current_status_replay(conn):
    # no events -> falls back to the entity row's initial_status
    conn.execute(
        "INSERT INTO claim(clm_id, statement, initial_status, created_at)"
        " VALUES ('clm_a','s','draft','t')")
    assert ledger.current_status(conn, "claim", "clm_a") == "draft"
    # establish the imported initial state, then append two transitions
    ledger.append_event(conn, "claim", "clm_a", "draft", "u", "imported")
    ledger.append_event(conn, "claim", "clm_a", "active", "u", "r", from_status="draft")
    ledger.append_event(conn, "claim", "clm_a", "superseded", "u", "r", from_status="active")
    assert ledger.current_status(conn, "claim", "clm_a") == "superseded"


def test_transition_allowed_and_rejected(conn):
    clm = ledger.create_claim(conn, statement="s")
    assert ledger.current_status(conn, "claim", clm) == "draft"
    ledger.transition(conn, "claim", clm, "active", "u", "reviewed")
    assert ledger.current_status(conn, "claim", clm) == "active"
    # active->draft is not in the allowed set
    with pytest.raises(ValueError):
        ledger.transition(conn, "claim", clm, "draft", "u", "nope")


def test_transition_rejects_unknown_and_broken_chain(conn):
    with pytest.raises(ValueError, match="unknown claim entity"):
        ledger.transition(conn, "claim", "clm_missing", "active", "u", "nope")

    clm = ledger.create_claim(conn, statement="broken")
    conn.execute("DROP TRIGGER noguard_upd_ledger_event")
    conn.execute(
        "UPDATE ledger_event SET from_status='wrong'"
        " WHERE entity_type='claim' AND entity_id=?", (clm,))
    with pytest.raises(ValueError, match="discontinuous"):
        ledger.current_status(conn, "claim", clm)


def test_generated_insight_lifecycle(conn):
    rit = ledger.create_research_item(conn, queue_source="fred", title="update")
    ins = ledger.create_generated_insight(
        conn, research_item_id=rit, input_sha256=_sha64(), prompt_version="v1",
        generator="test", model="test-model", planned_vault_path="洞察/test.md")
    assert ledger.current_status(conn, "generated_insight", ins) == "queued"

    with pytest.raises(ValueError, match="illegal"):
        ledger.transition(conn, "generated_insight", ins, "published", "u", "skip")
    ledger.transition(conn, "generated_insight", ins, "generating", "u", "start")
    with pytest.raises(ValueError, match="without artifact"):
        ledger.transition(conn, "generated_insight", ins, "ready", "u", "done")

    ledger.create_insight_artifact(
        conn, ins_id=ins, content_sha256="b" * 64, local_path="/tmp/test.md",
        validation={"ok": True})
    ledger.transition(conn, "generated_insight", ins, "ready", "u", "validated")
    ledger.transition(conn, "generated_insight", ins, "published", "u", "verified")
    ledger.transition(conn, "generated_insight", ins, "superseded", "u", "revision")
    with pytest.raises(ValueError, match="illegal"):
        ledger.transition(conn, "generated_insight", ins, "published", "u", "revive")


def test_insight_provenance_fk_and_exactly_one_source(conn):
    rit = ledger.create_research_item(conn, queue_source="fred", title="update")
    ins = ledger.create_generated_insight(
        conn, research_item_id=rit, input_sha256=_sha64(), prompt_version="v1",
        generator="test", model="test-model", planned_vault_path="洞察/test.md")
    with pytest.raises(sqlite3.IntegrityError):
        ledger.create_insight_provenance(
            conn, ins_id=ins, source_type="evidence_snapshot", source_id="evi_missing")
    with pytest.raises(ValueError, match="unsupported"):
        ledger.create_insight_provenance(
            conn, ins_id=ins, source_type="video", source_id="youtube")


# ---------------------------------------------------------------------------
# Entity creators (row + 'created' event atomic)
# ---------------------------------------------------------------------------

def test_create_claim_atomic(conn):
    clm = ledger.create_claim(conn, statement="test claim",
                              alternatives=["x", "y"], evidence_ids=["evi_1"])
    assert conn.execute("SELECT 1 FROM claim WHERE clm_id=?", (clm,)).fetchone()
    ev = conn.execute(
        "SELECT to_status FROM ledger_event WHERE entity_type='claim' AND entity_id=?",
        (clm,)).fetchone()
    assert ev[0] == "draft"
    alts = json_loads(conn.execute(
        "SELECT alternative_explanations FROM claim WHERE clm_id=?", (clm,)).fetchone()[0])
    assert alts == ["x", "y"]


def test_create_forecast_fk_enforced(conn):
    clm = ledger.create_claim(conn, statement="s")
    fid = ledger.create_forecast(conn, claim_id=clm, metric_id="m",
                                 target_period="t", decision_rule="r",
                                 review_due_at="2026-12-01")
    assert conn.execute("SELECT claim_id FROM forecast WHERE fcst_id=?", (fid,)).fetchone()[0] == clm
    # FK: a forecast pointing at a non-existent claim must be rejected
    with pytest.raises(sqlite3.IntegrityError):
        ledger.create_forecast(conn, claim_id="clm_nope", metric_id="m",
                               target_period="t", decision_rule="r",
                               review_due_at="2026-12-01")


def test_record_failure_queryable(conn):
    ledger.record_failure(conn, source="cn_stats_pmi", series="_period",
                          error_class="discover_error", detail="SSL EOF",
                          last_valid_evi="evi_old")
    row = conn.execute(
        "SELECT to_status, reason FROM ledger_event"
        " WHERE entity_type='source' AND entity_id='cn_stats_pmi/_period'").fetchone()
    assert row[0] == "failed"
    assert "SSL EOF" in row[1] and "evi_old" in row[1]


def json_loads(s):
    import json
    return json.loads(s)


# ---------------------------------------------------------------------------
# Acceptance gate 1: triggers forbid UPDATE/DELETE on all 7 tables
# ---------------------------------------------------------------------------

def test_trigger_rejects_update_delete(conn):
    # populate one row per entity table
    evi = ledger.create_evidence_snapshot(
        conn, source_url="u", published_at="p", observed_period="op",
        metric_id="m", value=1.0, unit="x", content_sha256=_sha64(),
        raw_path="/r", included=["m"])
    clm = ledger.create_claim(conn, statement="s")
    fid = ledger.create_forecast(conn, claim_id=clm, metric_id="m",
                                 target_period="t", decision_rule="r",
                                 review_due_at="d")
    rev = ledger.create_review(conn, forecast_id=fid)
    imp = ledger.create_client_implication(conn, claim_id=clm)
    rit = ledger.create_research_item(conn, queue_source="q", title="t")
    ins = ledger.create_generated_insight(
        conn, research_item_id=rit, input_sha256=_sha64(), prompt_version="v1",
        generator="test", model="test-model", planned_vault_path="洞察/test.md")
    art = ledger.create_insight_artifact(
        conn, ins_id=ins, content_sha256="b" * 64, local_path="/tmp/test.md",
        validation={"ok": True})
    prv = ledger.create_insight_provenance(
        conn, ins_id=ins, source_type="evidence_snapshot", source_id=evi)
    att = ledger.record_insight_attempt(
        conn, ins_id=ins, stage="generate", outcome="success")

    cases = [
        ("evidence_snapshot", "evi_id", evi),
        ("claim", "clm_id", clm),
        ("forecast", "fcst_id", fid),
        ("review", "rev_id", rev),
        ("client_implication", "imp_id", imp),
        ("research_item", "rit_id", rit),
        ("generated_insight", "ins_id", ins),
        ("insight_artifact", "art_id", art),
        ("insight_provenance", "prv_id", prv),
        ("insight_attempt", "att_id", att),
    ]
    for table, pk, val in cases:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"UPDATE {table} SET {pk}={pk} WHERE {pk}=?", (val,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(f"DELETE FROM {table} WHERE {pk}=?", (val,))
    # ledger_event itself
    evt = conn.execute("SELECT evt_id FROM ledger_event LIMIT 1").fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE ledger_event SET actor='x' WHERE evt_id=?", (evt,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM ledger_event WHERE evt_id=?", (evt,))


# ---------------------------------------------------------------------------
# Acceptance gate 2: 10-min reconstruction via self-contained claim card
# ---------------------------------------------------------------------------

def test_seed_and_reconstruction(conn):
    clm = ledger.seed_phase1(conn)
    assert clm.startswith("clm_")
    card = ledger.render_claim_card(conn, clm)
    # self-contained: every reconstruction need is inlined in the card
    assert "总需求仍弱" in card
    assert "sha256:" in card               # evidence content hash
    assert "http" in card                  # source URL
    assert "raw:" in card                  # evidence file path
    assert "threshold: -5.0" in card       # pre-registered forecast threshold
    assert "review due: 2026-08-25" in card
    assert "cscoheru(author) / cscoheru(reviewer)" in card  # dual-hat self-sign (D1)
    assert "status: active" in card        # forecast + implication activated
    # the cited evidence sha matches the real file on disk
    real_sha = ledger._sha256_file(
        os.path.join(paths.SNAPS, "cn_stats_inv", "release-2026-06.txt"))
    assert real_sha in card


def test_seed_idempotent(conn):
    clm1 = ledger.seed_phase1(conn)
    clm2 = ledger.seed_phase1(conn)
    assert clm1 == clm2
    # second seed must not duplicate rows
    assert conn.execute("SELECT COUNT(*) FROM claim").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM forecast").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM client_implication").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# Regression: _yoy double-suffix bug (run.py:166-167)
# ---------------------------------------------------------------------------

def test_yoy_key_regression():
    import run
    # the bug: a series already named cpi_yoy became cpi_yoy_yoy
    assert run._yoy_key("cpi_yoy") == "cpi_yoy"
    assert run._yoy_key("gdp") == "gdp_yoy"
    assert run._yoy_key("inv_total_yoy") == "inv_total_yoy"
