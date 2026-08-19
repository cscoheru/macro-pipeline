"""One-shot: queue insights for source+period pairs that were missed while
insights.enabled was off (the 8/14–8/18 observation window).

The collection runs of those days still saved evidence_snapshot rows and a
research_item, but skipped the `if insights_on and rit_id:` branch that would
have built the fact pack and inserted the generated_insight row. This script
reconstructs `updates` from evidence_snapshot + readings cache and replays
the queueing through run._queue_source_insight.

The next `python3 run.py --insights-only` then drains the queue normally
(model -> validate -> publish) so we get the same hard-validation as fresh
data, not a silent re-process of stale insights.
"""
import argparse
import os
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import readings_cache  # noqa: E402
import run as run_mod  # noqa: E402
import store  # noqa: E402

CONFIG = os.path.join(os.path.dirname(__file__), "..", "config", "sources.yaml")


def _evidence_for(conn, source, period):
    """evidence_snapshot rows for source + period with non-null value."""
    return conn.execute(
        "SELECT evi_id, metric_id, value, unit FROM evidence_snapshot "
        " WHERE metric_id LIKE ? AND observed_period=?"
        "   AND value IS NOT NULL",
        (f"{source}:%", period),
    ).fetchall()


def _research_item_for(conn, source):
    """Most recent research_item for this source."""
    return conn.execute(
        "SELECT rit_id, title FROM research_item WHERE queue_source=?"
        " ORDER BY created_at DESC LIMIT 1",
        (source,),
    ).fetchone()


def _reconstruct_updates(source, period, evi_rows, cache):
    """Build the updates list that process_cn_release would have built.

    Each entry has the same shape that evaluate_triggers / build_fact_pack
    expect: id, name, source, stats {value, yoy_pct, ...}, evi_id.
    """
    updates = []
    for evi_id, metric_id, value, unit in evi_rows:
        short_id = metric_id.split(":", 1)[1]
        # yoy_pct: prefer the cache entry ONLY if it is for the same period
        # we are backfilling. The cache stores the latest reading per metric;
        # using it without a period check would splice a future month into a
        # historical fact pack. If no period-matching cache entry exists,
        # leave yoy None — better than guessing from the level (unemployment
        # rate 2.5% would silently become "2.5% YoY").
        cache_entry = cache.get(metric_id, {})
        yoy = None
        if cache_entry.get("period") == period:
            yoy = cache_entry.get("yoy_pct")
        name = cache_entry.get("name") or short_id
        stats = {
            "value": value,
            "yoy_pct": yoy,
            "mom_pct": None,
            "trend": "—",
            "date": period,
        }
        updates.append({
            "id": short_id,
            "name": name,
            "unit": unit,
            "economy": "cn",
            "source": source,
            "stats": stats,
            "evi_id": evi_id,
            "revision": False,
        })
    return updates


def queue_source(source, period):
    """Queue one source+period. Returns ins_id or None."""
    cache = readings_cache.load()
    cfg = yaml.safe_load(open(CONFIG, encoding="utf-8"))
    triggers = cfg.get("triggers", [])

    conn = store._connect()
    try:
        evi_rows = _evidence_for(conn, source, period)
        if not evi_rows:
            print(f"{source}/{period}: no evidence_snapshot rows, skipping")
            return None
        rit = _research_item_for(conn, source)
        if not rit:
            print(f"{source}/{period}: no research_item found, skipping")
            return None
        rit_id, rit_title = rit
        # Make sure the research_item is for this period — backfill only
        # queues insights for periods that aren't yet represented in any
        # generated_insight for this source.
        existing = conn.execute(
            "SELECT 1 FROM insight_provenance p"
            " JOIN evidence_snapshot e ON e.evi_id = p.evi_id"
            " WHERE e.metric_id LIKE ? AND e.observed_period=?"
            " LIMIT 1",
            (f"{source}:%", period),
        ).fetchone()
        if existing:
            print(f"{source}/{period}: already has provenance, skipping (idempotent)")
            return None
    finally:
        conn.close()

    updates = _reconstruct_updates(source, period, evi_rows, cache)
    flags = run_mod.evaluate_triggers(triggers, updates)
    ins_id = run_mod._queue_source_insight(
        source, updates, flags, cache, rit_id,
    )
    if ins_id:
        print(f"{source}/{period}: queued {ins_id} "
              f"({len(updates)} metrics, {len(flags)} flags) — rit={rit_title!r}")
    else:
        print(f"{source}/{period}: queue failed (see warnings)")
    return ins_id


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", action="append", default=[],
                    help="source to backfill (repeatable); default cn_pbc cn_stats_inv")
    ap.add_argument("--period", default="2026-07",
                    help="observed period to backfill; default 2026-07")
    args = ap.parse_args()
    sources = args.source or ["cn_pbc", "cn_stats_inv"]
    queued = []
    for src in sources:
        ins_id = queue_source(src, args.period)
        if ins_id:
            queued.append((src, ins_id))
    print(f"\nqueued {len(queued)} insight(s); run `python3 run.py --insights-only` to drain")


if __name__ == "__main__":
    main()