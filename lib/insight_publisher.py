"""Idempotent outbox publisher for generated insights.

PUT the rendered artifact to its planned vault path, GET-readback verify the
sha256, then advance the ledger to 'published'. Re-publishing an already
published insight is a no-op. A successful PUT followed by a ledger failure
leaves the insight 'ready'; the next run re-PUTs the same content to the same
path and completes — generation success is never conflated with publication
success.
"""
import hashlib

import ledger


class PublishError(RuntimeError):
    def __init__(self, message, *, retryable=False, error_class="publish_error"):
        super().__init__(message)
        self.retryable = retryable
        self.error_class = error_class


def _latest_artifact(conn, ins_id):
    return conn.execute(
        "SELECT content_sha256, local_path FROM insight_artifact"
        " WHERE ins_id=? ORDER BY created_at DESC, art_id DESC LIMIT 1",
        (ins_id,),
    ).fetchone()


def _planned_path(conn, ins_id):
    row = conn.execute(
        "SELECT planned_vault_path FROM generated_insight WHERE ins_id=?",
        (ins_id,),
    ).fetchone()
    return row[0] if row else None


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def publish(conn, *, ins_id, writer, actor="system"):
    """Publish a ready insight idempotently; returns True once published."""
    status = ledger.current_status(conn, "generated_insight", ins_id)
    if status is None:
        raise PublishError(f"unknown insight {ins_id}", error_class="unknown_insight")
    if status == "published":
        return True
    if status != "ready":
        raise PublishError(
            f"insight {ins_id} status {status!r} is not publishable",
            error_class="invalid_state",
        )

    artifact = _latest_artifact(conn, ins_id)
    if artifact is None:
        raise PublishError(
            f"ready insight {ins_id} has no artifact",
            error_class="missing_artifact",
        )
    content_sha, local_path = artifact

    try:
        with open(local_path, encoding="utf-8") as handle:
            content = handle.read()
    except OSError as exc:
        raise PublishError(
            f"artifact file unreadable: {local_path}",
            retryable=True, error_class="artifact_io",
        ) from exc
    if _sha256(content) != content_sha:
        raise PublishError(
            "artifact content hash does not match recorded sha256",
            error_class="corrupt_artifact",
        )

    planned_path = _planned_path(conn, ins_id)

    # The writer is a process boundary (Obsidian REST); any failure there is a
    # retryable technical fault, not a content fault. A broad catch keeps the
    # failure mode uniform and lets a FakeVaultWriter signal errors generically.
    try:
        writer.put_pipeline(planned_path, content)
    except Exception as exc:
        raise PublishError(
            "vault put failed", retryable=True, error_class="put_failed",
        ) from exc
    try:
        fetched = writer.get_pipeline(planned_path)
    except Exception as exc:
        raise PublishError(
            "vault readback failed", retryable=True, error_class="readback_failed",
        ) from exc
    if fetched is None or _sha256(fetched) != content_sha:
        raise PublishError(
            "vault readback hash mismatch",
            retryable=True, error_class="readback_mismatch",
        )

    # Last step: only advance the ledger after the artifact is durably visible
    # in the vault and readback-verified. If this transition fails (or the host
    # crashes right before commit), the insight stays 'ready' and the next run
    # re-PUTs identical content to the same path — idempotent completion.
    ledger.transition(
        conn, "generated_insight", ins_id, "published", actor,
        f"published to {planned_path}; readback verified",
    )
    _supersede_predecessor(conn, ins_id, actor=actor)
    return True


def _supersede_predecessor(conn, ins_id, *, actor):
    """After a revision article publishes, retire the article it replaces.

    The predecessor only moves to 'superseded' from 'published' — if it never
    published (needs_review etc.) it keeps its status and the new article
    simply coexists with it.
    """
    row = conn.execute(
        "SELECT supersedes_id FROM generated_insight WHERE ins_id=?", (ins_id,),
    ).fetchone()
    predecessor = row[0] if row else None
    if not predecessor:
        return
    try:
        ledger.transition(
            conn, "generated_insight", predecessor, "superseded", actor,
            f"superseded by revision {ins_id}",
        )
    except ValueError:
        # Predecessor is not 'published' (or already superseded): nothing to do.
        pass
