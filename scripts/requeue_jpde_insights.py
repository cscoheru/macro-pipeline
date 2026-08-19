"""Rebuild + requeue the 4 JP/DE insights whose fact packs were built when
their sources were missing from OFFICIAL_SOURCES (now registered).

Path mirrors run.py:_queue_source_insight: rebuild the fact pack from the same
evidence ids (official_primary now computes true), persist it, insert a NEW
queued generated_insight row. Old rows stay needs_review as a historical
record (append-only ledger forbids edits).
"""
import sys
sys.path.insert(0, 'lib')
sys.path.insert(0, '.')
import store, ledger, insight_context, insight_render
import insight_provider
from run import _persist_fact_pack, _insight_generator_name, _insight_model_name

OLD_IDS = [
    "ins_01a01a0bba71732c826123a1750d0353",  # de_cpi
    "ins_01a01a0cbeae74a38e752a1b56d369fa",  # de_ppi
    "ins_01a01a0dddda75e696541b9de32e99ec",  # de_unrate
    "ins_01a01a2a881371a681aa8ff4615a7120",  # jp_gdp
]

conn = store._connect()
try:
    prompt_version = insight_provider.load_prompt_and_schema()[2]
    for old_id in OLD_IDS:
        row = conn.execute(
            "SELECT research_item_id FROM generated_insight WHERE ins_id=?",
            (old_id,)).fetchone()
        if not row:
            print(f"SKIP {old_id}: not found")
            continue
        rit_id = row[0]
        evi_rows = conn.execute(
            "SELECT evi_id FROM insight_provenance WHERE ins_id=? "
            "AND role='evidence' ORDER BY ordinal",
            (old_id,)).fetchall()
        evi_ids = [r[0] for r in evi_rows]

        fact_pack, new_sha = insight_context.build_fact_pack(
            conn, research_item_id=rit_id, evidence_ids=evi_ids)
        primaries = [e["official_primary"] for e in fact_pack["evidence"]]
        if not all(primaries):
            print(f"SKIP {old_id}: official_primary still {primaries}")
            continue
        print(f"{old_id}: official_primary={primaries}, new_sha={new_sha[:12]}")

        _persist_fact_pack(fact_pack, new_sha)
        new_id = ledger.new_id("generated_insight")
        planned = insight_render.planned_vault_path(new_id, fact_pack["as_of"])
        with conn:
            ledger.create_generated_insight(
                conn, research_item_id=rit_id, input_sha256=new_sha,
                prompt_version=prompt_version,
                generator=_insight_generator_name(),
                model=_insight_model_name(),
                planned_vault_path=planned,
                supersedes_id=None, ins_id=new_id)
            for index, evi_id in enumerate(evi_ids):
                ledger.create_insight_provenance(
                    conn, ins_id=new_id, source_type="evidence_snapshot",
                    source_id=evi_id, role="evidence", ordinal=index)
        print(f"  -> queued {new_id} ({planned})")
except Exception:
    import traceback; traceback.print_exc()
finally:
    conn.close()