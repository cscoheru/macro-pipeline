"""Drain the insight queue: generate, validate, render, then publish.

The runner never recomputes a fact pack. It loads the content-addressed fact
pack persisted at collection time and verifies its sha256 still equals the
input_sha256 recorded when the insight was queued — if they diverge, the
queued task is left in place with an attempt record rather than generating
against an unverified input.

Three failure modes map to three states:
  * retryable technical failure (provider down) -> back to 'queued' (auto-retry)
  * content failure (model output fails the gates) -> 'needs_review' (a human)
  * fact-pack integrity failure (hash mismatch) -> stays 'queued' with an
    attempt record (a storage fault, not a model fault — fixable on re-run)

Generation success is never conflated with publication success: publishing is
a separate, idempotent step (see insight_publisher).
"""
import json
import logging
import os

import insight_context
import insight_publisher
import insight_provider
import insight_render
import insight_validate
import ledger
import paths


def load_fact_pack(input_sha256, facts_dir=None):
    """Load a content-addressed fact pack by its input sha256."""
    path = os.path.join(facts_dir or paths.INSIGHT_FACTS, f"{input_sha256}.json")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _stored_input_sha(conn, ins_id):
    row = conn.execute(
        "SELECT input_sha256 FROM generated_insight WHERE ins_id=?", (ins_id,),
    ).fetchone()
    return row[0] if row else None


def _insights_in_status(conn, target_status, limit=None):
    """Insight ids currently in target_status, via one batch status query."""
    statuses = ledger.current_statuses(conn, "generated_insight")
    result = []
    for ins_id, input_sha in conn.execute(
        "SELECT ins_id, input_sha256 FROM generated_insight ORDER BY created_at"
    ).fetchall():
        if statuses.get(ins_id) == target_status:
            result.append((ins_id, input_sha))
            if limit is not None and len(result) >= limit:
                break
    return result


def _write_review(writer, ins_id, fact_pack, *, errors, reason,
                  response_path=None, response_sha=None):
    """Best-effort 待审/<ins_id>.md note. Never blocks the pipeline.

    The ledger stores only a detail hash, so this note is the human-readable,
    on-disk record of why an insight stalled: which gates failed, the fact-pack
    summary, and the local path to the raw model response.
    """
    if writer is None:
        return
    try:
        note = insight_render.render_review_note(
            ins_id, fact_pack, errors=errors, reason=reason,
            response_path=response_path, response_sha=response_sha,
        )
        writer.put_pipeline(f"待审/{ins_id}.md", note)
    except Exception:
        logging.getLogger(__name__).warning(
            "write review note for %s failed", ins_id, exc_info=True,
        )


def _handle_provider_error(conn, ins_id, fact_pack, exc, *, writer, actor):
    """Map a ProviderError to requeue (technical) or needs_review (fatal)."""
    ledger.record_insight_attempt(
        conn, ins_id=ins_id, stage="generate", outcome="error",
        error_class=exc.error_class, detail=str(exc),
    )
    if exc.retryable:
        ledger.transition(conn, "generated_insight", ins_id, "queued", actor,
                          f"retryable provider failure: {exc.error_class}")
        outcome = "queued"
    else:
        ledger.transition(conn, "generated_insight", ins_id, "needs_review",
                          actor, f"provider failure: {exc.error_class}")
        _write_review(
            writer, ins_id, fact_pack, errors=[str(exc)],
            reason=f"provider failure: {exc.error_class}",
        )
        outcome = "needs_review"
    conn.commit()
    return outcome


def _handle_validation_failure(conn, ins_id, fact_pack, result, *, writer,
                               actor, response_path, response_sha):
    ledger.record_insight_attempt(
        conn, ins_id=ins_id, stage="validate", outcome="needs_review",
        error_class="validation_failed", detail="; ".join(result.errors),
    )
    ledger.transition(conn, "generated_insight", ins_id, "needs_review", actor,
                      "validation failed")
    _write_review(
        writer, ins_id, fact_pack, errors=list(result.errors),
        reason="validation failed",
        response_path=response_path, response_sha=response_sha,
    )
    conn.commit()
    return "needs_review"


def _finalize_ready(conn, ins_id, document, fact_pack, result, *, stored_sha,
                    prompt_version, generated_at, actor):
    rendered = insight_render.render_markdown(
        document, fact_pack, ins_id=ins_id, input_sha256=stored_sha,
        prompt_version=prompt_version, generated_at=generated_at,
    )
    local_path = insight_render.persist_artifact(rendered)
    ledger.create_insight_artifact(
        conn, ins_id=ins_id, content_sha256=rendered.content_sha256,
        local_path=local_path, validation=result.as_dict(),
    )
    ledger.transition(conn, "generated_insight", ins_id, "ready", actor,
                      "validated and rendered")
    ledger.record_insight_attempt(
        conn, ins_id=ins_id, stage="render", outcome="ok",
    )
    conn.commit()
    return "ready"


def process_one(conn, *, ins_id, fact_pack, provider, prompt, schema,
                prompt_version, writer=None, actor="system", generated_at=None):
    """Advance one queued insight through generate -> validate -> render.

    Thin state-machine dispatcher: guards + generation + branch dispatch all
    live in the helpers above. Returns the to_status reached: 'ready',
    'needs_review', or 'queued'. Non-queued insights are returned unchanged.
    """
    status = ledger.current_status(conn, "generated_insight", ins_id)
    if status is None:
        raise ValueError(f"unknown insight {ins_id}")
    if status != "queued":
        return status

    stored_sha = _stored_input_sha(conn, ins_id)
    if insight_context.content_sha256(fact_pack) != stored_sha:
        ledger.record_insight_attempt(
            conn, ins_id=ins_id, stage="build", outcome="error",
            error_class="fact_pack_hash_mismatch",
            detail=f"expected {stored_sha}",
        )
        conn.commit()
        return "queued"

    ledger.transition(conn, "generated_insight", ins_id, "generating", actor,
                      "generation started")
    # Commit before calling the provider: the model call runs 90s+ with
    # retries, and holding the SQLite write transaction that long blocks
    # concurrent collectors. If the process dies mid-generate, the insight
    # stays 'generating' and recover_stuck_generating() requeues it on the
    # next drain.
    conn.commit()
    try:
        document = provider.generate(fact_pack, prompt=prompt, schema=schema)
    except insight_provider.ProviderError as exc:
        return _handle_provider_error(
            conn, ins_id, fact_pack, exc, writer=writer, actor=actor,
        )

    # Persist the raw response before validation so even malformed output is
    # auditable. Best-effort: a disk failure must not block the pipeline.
    try:
        response_path, response_sha = insight_render.persist_response(document)
    except (OSError, TypeError, ValueError):
        response_path = response_sha = None

    result = insight_validate.validate_output(document, fact_pack, schema=schema)
    if not result.ok:
        return _handle_validation_failure(
            conn, ins_id, fact_pack, result, writer=writer, actor=actor,
            response_path=response_path, response_sha=response_sha,
        )
    return _finalize_ready(
        conn, ins_id, document, fact_pack, result, stored_sha=stored_sha,
        prompt_version=prompt_version, generated_at=generated_at, actor=actor,
    )


def publish_ready(conn, *, writer, actor="system"):
    """Publish every insight currently 'ready'. Returns (published, failures)."""
    published, failures = 0, []
    for ins_id, _ in _insights_in_status(conn, "ready"):
        try:
            insight_publisher.publish(conn, ins_id=ins_id, writer=writer, actor=actor)
        except (insight_publisher.PublishError, ValueError) as exc:
            # ValueError: ledger.transition state-machine violations escaping
            # publish(); they carry no error_class attribute.
            error_class = getattr(exc, "error_class", "invalid_transition")
            ledger.record_insight_attempt(
                conn, ins_id=ins_id, stage="publish", outcome="error",
                error_class=error_class, detail=str(exc),
            )
            conn.commit()
            failures.append((ins_id, error_class))
            continue
        # publish() itself never commits — persist each success so a later
        # failure or an abandoned connection cannot roll back a vault write
        # that already happened (vault PUT and ledger event must not diverge).
        conn.commit()
        published += 1
    return published, failures


def recover_stuck_generating(conn, *, actor="system"):
    """Requeue insights left in 'generating' by an interrupted run.

    Safe only because a single launchd process drains the queue at a time —
    a 'generating' row at drain start means the previous process died
    between the commit of 'generating' and the next transition, never that
    another process is mid-generation. Returns the requeued insight ids.
    """
    requeued = []
    for ins_id, _ in _insights_in_status(conn, "generating"):
        try:
            ledger.transition(
                conn, "generated_insight", ins_id, "queued", actor,
                "recovered after interrupted run",
            )
            conn.commit()
            requeued.append(ins_id)
        except ValueError:
            logging.getLogger(__name__).warning(
                "recover %s from generating failed", ins_id, exc_info=True,
            )
    return requeued


def drain(conn, *, provider, writer, fact_pack_loader=None, prompt=None,
          schema=None, prompt_version=None, max_insights=None, actor="system",
          auto_publish=False):
    """Drain queued insights through generation, then publish all ready.

    fact_pack_loader(ins_id, input_sha256) -> fact_pack dict; defaults to the
    content-addressed INSIGHT_FACTS store. Returns a notification-friendly
    summary: published / needs_review / requeued / failed counts.
    """
    if prompt is None or schema is None or prompt_version is None:
        prompt, schema, prompt_version = insight_provider.load_prompt_and_schema()
    loader = fact_pack_loader or (lambda ins_id, sha: load_fact_pack(sha))
    recover_stuck_generating(conn, actor=actor)

    summary = {
        "published": 0, "needs_review": 0, "requeued": 0, "failed": 0,
    }

    for ins_id, stored_sha in _insights_in_status(conn, "queued", limit=max_insights):
        try:
            fact_pack = loader(ins_id, stored_sha)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            ledger.record_insight_attempt(
                conn, ins_id=ins_id, stage="build", outcome="error",
                error_class="fact_pack_missing", detail=str(exc),
            )
            conn.commit()
            summary["failed"] += 1
            continue
        outcome = process_one(
            conn, ins_id=ins_id, fact_pack=fact_pack, provider=provider,
            prompt=prompt, schema=schema, prompt_version=prompt_version,
            writer=writer, actor=actor,
        )
        if outcome == "ready":
            pass  # counted as published below
        elif outcome == "needs_review":
            summary["needs_review"] += 1
        elif outcome == "queued":
            summary["requeued"] += 1
        else:
            summary["failed"] += 1

    if auto_publish:
        published, failures = publish_ready(conn, writer=writer, actor=actor)
        summary["published"] = published
        summary["failed"] += len(failures)
    return summary


def summarize(conn):
    """Query-friendly snapshot of the insight queue for ops and notifications.

    Statuses are replay-derived (no status column), so this scans every row.
    Returns counts per state, the oldest queued row's created_at (backlog age),
    and the most recent non-ok attempt's error_class (or None).
    """
    counts = {
        "queued": 0, "generating": 0, "ready": 0,
        "needs_review": 0, "published": 0, "superseded": 0,
    }
    oldest_queued = None
    rows = conn.execute(
        "SELECT ins_id, created_at FROM generated_insight ORDER BY created_at",
    ).fetchall()
    for ins_id, created_at in rows:
        status = ledger.current_status(conn, "generated_insight", ins_id)
        if status in counts:
            counts[status] += 1
        if status == "queued" and (oldest_queued is None or created_at < oldest_queued):
            oldest_queued = created_at
    last_error_class = None
    err = conn.execute(
        "SELECT error_class FROM insight_attempt"
        " WHERE outcome IN ('error','needs_review')"
        " ORDER BY occurred_at DESC LIMIT 1",
    ).fetchone()
    if err:
        last_error_class = err[0]
    return {
        **counts,
        "oldest_queued_created_at": oldest_queued,
        "last_error_class": last_error_class,
    }
