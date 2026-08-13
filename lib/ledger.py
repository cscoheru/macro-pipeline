"""Strict append-only judgement ledger (Phase 1).

Event-sourced: entity rows are INSERT-once; status is derived by replaying
ledger_event rows. SQLite triggers forbid UPDATE/DELETE on all 7 tables, so
the only legal way to change state is append_event() inside transition().

Immutability is structural, not defensive: because legal code never UPDATEs an
entity, the triggers can blanket-ban every UPDATE/DELETE without distinguishing
legitimate transitions from tampering.

See docs/plans/phase1-judgement-ledger.md (S2 architecture, S2a hardening).
"""
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths

# ---------------------------------------------------------------------------
# IDs - UUIDv7 (time-ordered) + type prefix. Python 3.14 has uuid.uuid7().
# ---------------------------------------------------------------------------

_PREFIXES = {
    "evidence_snapshot": "evi",
    "claim": "clm",
    "forecast": "fcst",
    "review": "rev",
    "client_implication": "imp",
    "research_item": "rit",
    "ledger_event": "evt",
}

# Entity tables that carry an initial_status column (ledger_event does not).
_PK = {
    "evidence_snapshot": "evi_id",
    "claim": "clm_id",
    "forecast": "fcst_id",
    "review": "rev_id",
    "client_implication": "imp_id",
    "research_item": "rit_id",
}


def new_id(entity_type: str) -> str:
    """Time-ordered id with type prefix, e.g. 'clm_01923afb...'."""
    return f"{_PREFIXES[entity_type]}_{uuid.uuid7().hex}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Schema (7 append-only tables + FK + immutability triggers)
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ledger_event (
  evt_id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
  from_status TEXT, to_status TEXT NOT NULL,
  actor TEXT, reason TEXT, occurred_at TEXT NOT NULL,
  payload_sha256 TEXT
);
CREATE TABLE IF NOT EXISTS evidence_snapshot (
  evi_id TEXT PRIMARY KEY,
  source_url TEXT, publisher TEXT, published_at TEXT, retrieved_at TEXT,
  observed_period TEXT, metric_id TEXT, value REAL, unit TEXT,
  methodology_version TEXT,
  content_sha256 TEXT NOT NULL, raw_path TEXT NOT NULL,
  included_metrics TEXT, missing_metrics TEXT,
  initial_status TEXT NOT NULL DEFAULT 'created',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claim (
  clm_id TEXT PRIMARY KEY,
  as_of_time TEXT, statement TEXT NOT NULL, scope TEXT, mechanism TEXT,
  alternative_explanations TEXT,
  confidence TEXT, initial_status TEXT NOT NULL DEFAULT 'draft',
  supersedes_id TEXT REFERENCES claim(clm_id),
  evidence_ids TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS forecast (
  fcst_id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL REFERENCES claim(clm_id),
  metric_id TEXT, target_period TEXT,
  decision_rule TEXT NOT NULL, threshold REAL, direction TEXT,
  review_due_at TEXT NOT NULL,
  initial_status TEXT NOT NULL DEFAULT 'draft',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review (
  rev_id TEXT PRIMARY KEY,
  forecast_id TEXT NOT NULL REFERENCES forecast(fcst_id),
  reviewed_at TEXT, outcome TEXT,
  observed_evidence_id TEXT REFERENCES evidence_snapshot(evi_id),
  error_class_primary TEXT, error_class_secondary TEXT, rationale TEXT,
  initial_status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS client_implication (
  imp_id TEXT PRIMARY KEY,
  claim_id TEXT NOT NULL REFERENCES claim(clm_id),
  client_segment TEXT, action TEXT, trigger TEXT, stop_condition TEXT,
  decision_horizon TEXT, evidence_grade TEXT,
  reviewer_primary TEXT, reviewer_secondary TEXT,
  initial_status TEXT NOT NULL DEFAULT 'draft',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_item (
  rit_id TEXT PRIMARY KEY,
  queue_source TEXT, source_event_id TEXT REFERENCES ledger_event(evt_id),
  title TEXT, priority TEXT, claim_id TEXT REFERENCES claim(clm_id),
  initial_status TEXT NOT NULL DEFAULT 'queued',
  claimed_by TEXT, claimed_at TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_entity
  ON ledger_event(entity_type, entity_id, occurred_at, evt_id);
"""

# All 7 tables are append-only: triggers blanket-ban UPDATE/DELETE.
# Legal code never UPDATEs an entity; state moves only via append_event().
_ENTITIES = [
    "evidence_snapshot", "claim", "forecast", "review",
    "client_implication", "research_item", "ledger_event",
]


def _triggers_sql() -> str:
    parts = []
    for t in _ENTITIES:
        parts.append(
            f"CREATE TRIGGER IF NOT EXISTS noguard_upd_{t} BEFORE UPDATE ON {t}\n"
            f"BEGIN SELECT RAISE(ABORT, 'ledger table {t} is append-only: UPDATE forbidden'); END;"
        )
        parts.append(
            f"CREATE TRIGGER IF NOT EXISTS noguard_del_{t} BEFORE DELETE ON {t}\n"
            f"BEGIN SELECT RAISE(ABORT, 'ledger table {t} is append-only: DELETE forbidden'); END;"
        )
    return "\n".join(parts)


def init_schema(conn):
    """Create all 7 ledger tables + immutability triggers. Idempotent."""
    conn.executescript(_SCHEMA_SQL)
    conn.executescript(_triggers_sql())


# ---------------------------------------------------------------------------
# State machine - allowed (from_status, to_status) transitions per entity.
# ---------------------------------------------------------------------------

ALLOWED = {
    "research_item": {
        ("queued", "claimed"), ("claimed", "completed"),
        ("queued", "blocked"), ("blocked", "claimed"),
    },
    "claim": {("draft", "active"), ("active", "superseded")},
    "forecast": {
        ("draft", "active"), ("active", "due"),
        ("due", "hit"), ("due", "miss"), ("due", "partial"), ("due", "indeterminate"),
        ("hit", "closed"), ("miss", "closed"),
        ("partial", "closed"), ("indeterminate", "closed"),
        ("active", "closed"),
    },
    "client_implication": {("draft", "active"), ("active", "superseded")},
    "review": {("open", "completed")},
}


# ---------------------------------------------------------------------------
# Event primitives
# ---------------------------------------------------------------------------

def append_event(conn, entity_type, entity_id, to_status, actor, reason,
                 from_status=None, payload=None):
    """Append one transition to ledger_event. No entity row is touched."""
    payload_sha = None
    if payload is not None:
        payload_sha = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
    conn.execute(
        "INSERT INTO ledger_event"
        "(evt_id, entity_type, entity_id, from_status, to_status, actor,"
        " reason, occurred_at, payload_sha256) VALUES (?,?,?,?,?,?,?,?,?)",
        (new_id("ledger_event"), entity_type, entity_id, from_status, to_status,
         actor, reason, _now(), payload_sha))


def current_status(conn, entity_type, entity_id):
    """Derive status by replaying the entity's event chain (newest to_status),
    falling back to the entity row's initial_status if no events exist."""
    cur = conn.execute(
        "SELECT to_status FROM ledger_event WHERE entity_type=? AND entity_id=?"
        " ORDER BY occurred_at ASC, evt_id ASC",
        (entity_type, entity_id))
    rows = [r[0] for r in cur.fetchall()]
    if rows:
        return rows[-1]
    pk = _PK.get(entity_type)
    if not pk:
        return None
    row = conn.execute(
        f"SELECT initial_status FROM {entity_type} WHERE {pk}=?", (entity_id,)).fetchone()
    return row[0] if row else None


def transition(conn, entity_type, entity_id, to_status, actor, reason,
               allowed=None):
    """Validate from->to is allowed, then append the event. Raises ValueError
    on an illegal transition. Call within a transaction (`with conn:`)."""
    allowed = allowed if allowed is not None else ALLOWED.get(entity_type, set())
    cur = conn.execute(
        "SELECT to_status FROM ledger_event WHERE entity_type=? AND entity_id=?"
        " ORDER BY occurred_at ASC, evt_id ASC",
        (entity_type, entity_id))
    rows = [r[0] for r in cur.fetchall()]
    current = rows[-1] if rows else None
    if (current, to_status) not in allowed:
        raise ValueError(
            f"illegal {entity_type} transition: {current!r} -> {to_status!r}"
            f" (entity {entity_id})")
    append_event(conn, entity_type, entity_id, to_status, actor, reason,
                 from_status=current)


# ---------------------------------------------------------------------------
# Entity creators - INSERT row + first 'created' event, same transaction.
# Callers must wrap in `with conn:` for atomicity.
# ---------------------------------------------------------------------------

def create_evidence_snapshot(conn, *, source_url, published_at, observed_period,
                             metric_id, value, unit, content_sha256, raw_path,
                             included=None, missing=None, publisher=None,
                             retrieved_at=None, methodology_version=None,
                             actor="system", reason="snapshot acquired"):
    eid = new_id("evidence_snapshot")
    conn.execute(
        "INSERT INTO evidence_snapshot"
        "(evi_id, source_url, publisher, published_at, retrieved_at, observed_period,"
        " metric_id, value, unit, methodology_version, content_sha256, raw_path,"
        " included_metrics, missing_metrics, initial_status, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, source_url, publisher, published_at, retrieved_at, observed_period,
         metric_id, value, unit, methodology_version, content_sha256, raw_path,
         json.dumps(included or [], ensure_ascii=False),
         json.dumps(missing or [], ensure_ascii=False),
         "created", _now()))
    append_event(conn, "evidence_snapshot", eid, "created", actor, reason)
    return eid


def create_claim(conn, *, statement, mechanism=None, alternatives=None,
                 evidence_ids=None, confidence=None, scope=None, as_of_time=None,
                 supersedes_id=None, actor="system", reason="claim drafted"):
    eid = new_id("claim")
    conn.execute(
        "INSERT INTO claim"
        "(clm_id, as_of_time, statement, scope, mechanism, alternative_explanations,"
        " confidence, supersedes_id, evidence_ids, initial_status, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (eid, as_of_time or _now(), statement, scope, mechanism,
         json.dumps(alternatives or [], ensure_ascii=False),
         confidence, supersedes_id,
         json.dumps(evidence_ids or [], ensure_ascii=False),
         "draft", _now()))
    append_event(conn, "claim", eid, "draft", actor, reason)
    return eid


def create_forecast(conn, *, claim_id, metric_id, target_period, decision_rule,
                    review_due_at, threshold=None, direction=None,
                    actor="system", reason="forecast registered"):
    eid = new_id("forecast")
    conn.execute(
        "INSERT INTO forecast"
        "(fcst_id, claim_id, metric_id, target_period, decision_rule, threshold,"
        " direction, review_due_at, initial_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (eid, claim_id, metric_id, target_period, decision_rule, threshold,
         direction, review_due_at, "draft", _now()))
    append_event(conn, "forecast", eid, "draft", actor, reason)
    return eid


def create_client_implication(conn, *, claim_id, segment=None, action=None,
                              trigger=None, stop_condition=None,
                              decision_horizon=None, grade=None,
                              reviewer_primary=None, reviewer_secondary=None,
                              actor="system", reason="implication drafted"):
    eid = new_id("client_implication")
    conn.execute(
        "INSERT INTO client_implication"
        "(imp_id, claim_id, client_segment, action, trigger, stop_condition,"
        " decision_horizon, evidence_grade, reviewer_primary, reviewer_secondary,"
        " initial_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (eid, claim_id, segment, action, trigger, stop_condition,
         decision_horizon, grade, reviewer_primary, reviewer_secondary,
         "draft", _now()))
    append_event(conn, "client_implication", eid, "draft", actor, reason)
    return eid


def create_research_item(conn, *, queue_source, title, priority="normal",
                         source_event_id=None, claim_id=None,
                         actor="system", reason="new source event queued"):
    eid = new_id("research_item")
    conn.execute(
        "INSERT INTO research_item"
        "(rit_id, queue_source, source_event_id, title, priority, claim_id,"
        " initial_status, claimed_by, claimed_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (eid, queue_source, source_event_id, title, priority, claim_id,
         "queued", None, None, _now()))
    append_event(conn, "research_item", eid, "queued", actor, reason)
    return eid


def record_failure(conn, *, source, series, error_class, detail,
                   last_valid_evi=None, actor="system"):
    """Persist a source acquisition failure as a queryable ledger event (G1).

    entity_type 'source' is virtual (no row table); failures are found via
    SELECT ... WHERE entity_type='source' AND entity_id LIKE 'src/series'.
    Never raises - it is called from exception paths where another error is active.
    """
    try:
        reason = f"{error_class}: {detail}"
        if last_valid_evi:
            reason += f" | last_valid_evi={last_valid_evi}"
        append_event(conn, "source", f"{source}/{series}", "failed", actor, reason)
    except Exception:
        # record_failure must never propagate out of an error-handling path.
        pass


# ---------------------------------------------------------------------------
# Read helpers + report card (self-contained: 10-min reconstruction medium)
# ---------------------------------------------------------------------------

def _row(conn, table, pk_col, pk_val):
    cur = conn.execute(f"SELECT * FROM {table} WHERE {pk_col}=?", (pk_val,))
    r = cur.fetchone()
    return {d[0]: r[i] for i, d in enumerate(cur.description)} if r else None


def _kv(label, val):
    return f"- **{label}:** {val}" if val is not None else None


def render_claim_card(conn, clm_id) -> str:
    """Self-contained markdown card for a claim: inlines evidence paths, source
    URLs, thresholds, forecasts and implications so reconstruction needs no
    sqlite query - just read the card."""
    c = _row(conn, "claim", "clm_id", clm_id)
    if not c:
        return f"<!-- claim {clm_id} not found -->\n"
    L = ["---",
         f"clm_id: {clm_id}",
         f"type: claim_card",
         f"generated: {_now()}",
         "---",
         f"# Claim: {c['statement']}", ""]
    for kv in (_kv("As of", c.get("as_of_time")),
               _kv("Scope", c.get("scope")),
               _kv("Confidence", c.get("confidence")),
               _kv("Mechanism", c.get("mechanism")),
               f"- **Status:** {current_status(conn, 'claim', clm_id)}",
               _kv("Supersedes", c.get("supersedes_id"))):
        if kv:
            L.append(kv)
    alts = json.loads(c.get("alternative_explanations") or "[]")
    if alts:
        L.append("- **Alternative explanations:**")
        L += [f"  - {a}" for a in alts]
    L.append("")

    evi_ids = json.loads(c.get("evidence_ids") or "[]")
    if evi_ids:
        L.append("## Evidence (cited)")
        for eid in evi_ids:
            ev = _row(conn, "evidence_snapshot", "evi_id", eid)
            if not ev:
                L.append(f"### {eid} — *(missing)*"); continue
            L.append(f"### {eid} — {ev.get('metric_id', '?')}")
            for kv in (_kv("Publisher", ev.get("publisher")),
                       f"- published: {ev.get('published_at')} | observed_period: {ev.get('observed_period')}",
                       f"- value: {ev.get('value')} {ev.get('unit') or ''}".rstrip(),
                       f"- sha256: `{ev.get('content_sha256')}`",
                       f"- raw: `{ev.get('raw_path')}`",
                       _kv("Source URL", ev.get("source_url"))):
                if kv:
                    L.append(kv)
            inc = json.loads(ev.get("included_metrics") or "[]")
            mis = json.loads(ev.get("missing_metrics") or "[]")
            L.append(f"- included: {inc} | missing: {mis}")
            L.append("")

    fcs = conn.execute("SELECT fcst_id FROM forecast WHERE claim_id=?", (clm_id,)).fetchall()
    if fcs:
        L.append("## Forecasts")
        for (fid,) in fcs:
            f = _row(conn, "forecast", "fcst_id", fid)
            L.append(f"### {fid} — {f.get('metric_id', '?')} @ {f.get('target_period', '?')}")
            for kv in (f"- rule: {f.get('decision_rule')}",
                       f"- threshold: {f.get('threshold')} | direction: {f.get('direction')}",
                       f"- review due: {f.get('review_due_at')}",
                       f"- status: {current_status(conn, 'forecast', fid)}"):
                if kv:
                    L.append(kv)
            L.append("")

    imps = conn.execute("SELECT imp_id FROM client_implication WHERE claim_id=?", (clm_id,)).fetchall()
    if imps:
        L.append("## Client implications")
        for (iid,) in imps:
            im = _row(conn, "client_implication", "imp_id", iid)
            L.append(f"### {iid} — {im.get('client_segment', '?')}")
            for kv in (_kv("Action", im.get("action")),
                       _kv("Trigger", im.get("trigger")),
                       _kv("Stop condition", im.get("stop_condition")),
                       _kv("Decision horizon", im.get("decision_horizon")),
                       _kv("Evidence grade", im.get("evidence_grade")),
                       f"- reviewers: {im.get('reviewer_primary')} / {im.get('reviewer_secondary')}",
                       f"- status: {current_status(conn, 'client_implication', iid)}"):
                if kv:
                    L.append(kv)
            L.append("")

    L.append("## Event history (replay)")
    evs = conn.execute(
        "SELECT occurred_at, actor, from_status, to_status, reason FROM ledger_event"
        " WHERE entity_type='claim' AND entity_id=? ORDER BY occurred_at, evt_id",
        (clm_id,)).fetchall()
    for ts, actor, frm, to, reason in evs:
        L.append(f"- {ts} | {actor} | {frm}->{to} | {reason}")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Phase 1 seed - thesis: "中国需求是否进入持续修复"
# Evidence hashes are computed from the real snapshot files on disk.
# ---------------------------------------------------------------------------

SEED_CLAIM_A = "货币宽松已启动但未传导至实体（M2 8.0% 升 vs M1 4.0% 弱）"
SEED_CLAIM_B = "总需求仍弱（固投 -5.7%、PMI 49.2<50、CPI 0.5% 低位）"


def _snapshot_meta(path):
    """Extract url/title from a CN release snapshot (process_cn_release format)."""
    url, title = None, None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("url="):
                    url = line[4:].strip()
                elif line.startswith("title="):
                    title = line[6:].strip()
                if url and title:
                    break
    except Exception:
        pass
    return url, title


def seed_phase1(conn):
    """Seed the Phase 1 thesis. Idempotent: returns existing claim_b if seeded.

    Creates 2 evidence snapshots (real sha256 of on-disk files), 2 claims,
    1 threshold-bearing forecast, 1 client implication activated via dual-hat
    self-sign (D1), and 1 research item exercising the queue state machine.
    """
    existing_a = conn.execute(
        "SELECT clm_id FROM claim WHERE statement=?", (SEED_CLAIM_A,)).fetchone()
    if existing_a:
        existing_b = conn.execute(
            "SELECT clm_id FROM claim WHERE statement=?", (SEED_CLAIM_B,)).fetchone()
        return existing_b[0] if existing_b else existing_a[0]

    pbc_path = os.path.join(paths.SNAPS, "cn_pbc", "release-2026-06.txt")
    inv_path = os.path.join(paths.SNAPS, "cn_stats_inv", "release-2026-06.txt")
    for p in (pbc_path, inv_path):
        if not os.path.exists(p):
            raise FileNotFoundError(f"seed evidence raw missing: {p}")
    pbc_url, _ = _snapshot_meta(pbc_path)
    inv_url, _ = _snapshot_meta(inv_path)

    with conn:
        evi_pbc = create_evidence_snapshot(
            conn, source_url=pbc_url, publisher="中国人民银行",
            published_at="2026-07", observed_period="2026-06",
            metric_id="cn_pbc:m2_m1_sf", value=8.0, unit="%",
            content_sha256=_sha256_file(pbc_path), raw_path=pbc_path,
            included=["M2同比8.0%", "M1同比4.0%", "社融"], missing=[],
            actor="system", reason="cn_pbc 2026上半年金融统计数据 发布稿")
        evi_inv = create_evidence_snapshot(
            conn, source_url=inv_url, publisher="国家统计局",
            published_at="2026-07", observed_period="2026-06",
            metric_id="cn_stats_inv:inv_total", value=-5.7, unit="%累计同比",
            content_sha256=_sha256_file(inv_path), raw_path=inv_path,
            included=["固投累计同比-5.7%"], missing=[],
            actor="system", reason="cn_stats_inv 1-6月固投 发布稿")

        clm_a = create_claim(
            conn, statement=SEED_CLAIM_A, scope="中国·货币",
            mechanism="M2 增速回升但 M1 仍弱，宽松未传导至企业活期与实体需求",
            alternatives=["M1 口径 2024 年调整（纳入个人活期等），弱读数部分为口径而非传导问题"],
            evidence_ids=[evi_pbc], confidence="中", actor="cscoheru(researcher)")
        clm_b = create_claim(
            conn, statement=SEED_CLAIM_B, scope="中国·总需求",
            mechanism="固投负增、PMI低于荣枯线、CPI低位，三指标共振指向总需求仍弱",
            alternatives=["PMI 季节性扰动（7月淡季）", "CPI 受食品基数与油价基数影响"],
            evidence_ids=[evi_inv], confidence="中", actor="cscoheru(researcher)")

        fcst = create_forecast(
            conn, claim_id=clm_b, metric_id="cn_stats_inv:inv_total",
            target_period="2026年1-7月",
            decision_rule="固投累计同比 >-5.0%=hit（修复确认） / <-6.0%=miss / 中间=partial",
            threshold=-5.0, direction="up", review_due_at="2026-08-25",
            actor="cscoheru(researcher)", reason="前置阈值，待统计局1-7月数据（约8/15）")
        transition(conn, "forecast", fcst, "active",
                   actor="cscoheru(researcher)", reason="forecast registered, awaiting 1-7月 data")

        imp = create_client_implication(
            conn, claim_id=clm_b, segment="逆周期布局型客户",
            action="维持基建链条观察仓，不加码",
            trigger="固投累计同比连续两月回升", stop_condition="PMI 跌破 48",
            decision_horizon="2026 Q3-Q4", grade="B",
            reviewer_primary="cscoheru(author)", reviewer_secondary="cscoheru(reviewer)",
            actor="cscoheru(author)", reason="implication drafted")
        # D1 dual-hat self-sign (same person, two roles, same day) - recorded
        # as two distinct events so the author/reviewer separation is auditable.
        transition(conn, "client_implication", imp, "active",
                   actor="cscoheru(reviewer)",
                   reason="dual-hat self-review（单人双签）: author=cscoheru, reviewer=cscoheru, same-day")

        rit = create_research_item(
            conn, queue_source="manual", title="中国需求是否进入持续修复（命题）",
            priority="high", claim_id=clm_b, actor="cscoheru(researcher)")
        transition(conn, "research_item", rit, "claimed",
                   actor="cscoheru(researcher)", reason="thesis claimed for drafting")
    return clm_b


if __name__ == "__main__":
    import store
    conn = store._connect()
    clm = seed_phase1(conn)
    print(f"seeded. primary claim (with forecast+implication) = {clm}\n")
    print(render_claim_card(conn, clm))
