"""PR-4 Phase 1 — Obsidian PUT → GET → SHA publisher (brief §11).

Mirrors the macro insight publisher's protocol (PUT, GET, SHA verify,
advance ledger) without importing it. `publish_page` is the single
write-side entry point; everything else is read-only.

The VaultWriter is an injectable protocol with two methods:
  - `put_pipeline(vault_path, content: str) -> None`
  - `get_pipeline(vault_path) -> str | None`

The default no-op writer is `DryRunVaultWriter` (records calls, never
touches the network). Tests inject `FakeVaultWriter` for failure
injection (SHA mismatch, network error, GET returns None). A real
`ObsidianLocalRestWriter` is intentionally NOT implemented in this
PR — the kickoff §2 prohibits real Obsidian PUTs without
`--apply --operator-authorized` and a separate live-smoke authorization.

This module NEVER imports `lib/insight_publisher.py` and NEVER reads /
writes `data/store.db`. See `docs/plans/pr4-obsidian-research-map.md`
§11.4 (S-4 audit guard) and `scripts/test_houchen_macro_isolation.py`.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
from dataclasses import dataclass
from typing import Optional, Protocol

import houchen_paths
import houchen_publish_paths
import houchen_schema


class VaultWriter(Protocol):
    """Two-method protocol that any backend must implement.

    `put_pipeline` MUST raise on transport failure; `get_pipeline` MUST
    return None (not raise) when the path does not exist. Both are
    expected to round-trip UTF-8 strings."""

    def put_pipeline(self, vault_path: str, content: str) -> None: ...
    def get_pipeline(self, vault_path: str) -> Optional[str]: ...


class ObsidianLocalRestWriter:
    """Obsidian Local REST API writer for the houchen research namespace.

    Uses `HOUCHEN_PUBLISH_*` from `config/houchen_publish.env` — never reads
    macro `config/rest.env` or imports `lib/vault_writer.py`.
    `put_pipeline` / `get_pipeline` accept the **full** vault path
    (e.g. `Research/世界苦茶/video/id.md`).
    """

    def __init__(self, base_url: str, api_token: str,
                 timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}"}

    def _url(self, vault_path: str) -> str:
        return f"{self.base_url}/vault/{urllib.parse.quote(vault_path)}"

    def put_pipeline(self, vault_path: str, content: str) -> None:
        import requests
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.put(
            self._url(vault_path),
            headers={
                **self._headers(),
                "Content-Type": "text/markdown; charset=utf-8",
            },
            data=content.encode("utf-8"),
            verify=False,
            timeout=self.timeout,
        )
        response.raise_for_status()

    def get_pipeline(self, vault_path: str) -> Optional[str]:
        import requests
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.get(
            self._url(vault_path),
            headers=self._headers(),
            verify=False,
            timeout=self.timeout,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.text


def obsidian_writer_from_env() -> ObsidianLocalRestWriter:
    """Build `ObsidianLocalRestWriter` from `houchen_publish.env`."""
    cfg = houchen_publish_paths.load_publish_config()
    timeout = float(cfg.get("HOUCHEN_PUBLISH_TIMEOUT", "15"))
    return ObsidianLocalRestWriter(
        base_url=cfg["HOUCHEN_PUBLISH_BASE_URL"],
        api_token=cfg["HOUCHEN_PUBLISH_API_TOKEN"],
        timeout=timeout,
    )


class DryRunVaultWriter:
    """No-network writer used by the default `publish` CLI (--dry-run).

    Records every call in `self.calls` so tests can assert what would
    have happened. Never raises; never touches the network or disk.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []   # (op, path, sha256)

    def put_pipeline(self, vault_path: str, content: str) -> None:
        self.calls.append(("put", vault_path, _sha256_text(content)))

    def get_pipeline(self, vault_path: str) -> Optional[str]:
        self.calls.append(("get", vault_path, ""))
        # Look up the last PUT to this path.
        for op, path, sha in reversed(self.calls):
            if op == "put" and path == vault_path:
                # We don't have the original text on hand. Real
                # readback is exercised by FakeVaultWriter in tests.
                return None
        return None

    def reset(self) -> None:
        self.calls.clear()


class PublishError(RuntimeError):
    """Raised by `publish_page` on a recoverable failure."""

    def __init__(self, message, *, retryable: bool = True,
                 error_class: str = "publish_error"):
        super().__init__(message)
        self.retryable = retryable
        self.error_class = error_class


@dataclass
class PublishResult:
    """Outcome of one `publish_page` call.

    `published` is True iff PUT → GET → SHA verified and the
    `publish_record` row was advanced to `published`. `error_class` is
    the structured reason on failure (or None on success).
    """

    page_id: str
    vault_path: str
    published: bool
    error_class: Optional[str] = None
    error_detail: Optional[str] = None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _publish_root_under_data_root(path: str) -> None:
    """Defensive: refuse to write anywhere outside the data root.

    The houchen_publish_paths.* helpers all anchor to publish_root(),
    so any caller using the helpers is safe. This is a belt-and-braces
    guard for code that bypasses the helpers.
    """
    canon_root = houchen_paths.resolve_data_root()
    canon_path = os.path.realpath(path)
    try:
        if os.path.commonpath([canon_root, canon_path]) != canon_root:
            raise PublishError(
                f"publish path escapes data root: {canon_path!r}",
                error_class="path_escape")
    except ValueError as exc:
        raise PublishError(
            f"publish path escapes data root: {canon_path!r}",
            error_class="path_escape") from exc


def _read_render_file(local_path: str, *, expected_sha: str) -> str:
    """Read the render file; raise PublishError if SHA mismatches.

    The mismatch case is `corrupt_artifact` (NOT retryable): the
    content is wrong on disk and re-running `render` will rewrite it.
    """
    try:
        with open(local_path, encoding="utf-8") as fh:
            content = fh.read()
    except OSError as exc:
        raise PublishError(
            f"render file unreadable: {local_path}",
            retryable=True, error_class="artifact_io") from exc
    actual_sha = _sha256_text(content)
    if actual_sha != expected_sha:
        raise PublishError(
            "render file sha256 does not match rendered_page.render_sha256",
            error_class="corrupt_artifact")
    return content


def _fetch_existing_record(conn, page_id: str,
                           vault_path: str) -> tuple | None:
    """Return the existing publish_record row, or None."""
    return conn.execute(
        "SELECT publish_id, status, vault_sha256 FROM publish_record"
        " WHERE page_id=? AND vault_path=?",
        (page_id, vault_path)).fetchone()


def publish_page(*, conn, page_id: str, vault_writer: VaultWriter,
                 actor: str = "system") -> PublishResult:
    """Idempotently publish one rendered_page.

    Returns PublishResult(published=True) on a fresh successful publish.
    Returns PublishResult(published=True) with no writer calls if the
    page was already published (no-op). Returns
    PublishResult(published=False) on a recoverable failure; the
    `publish_record` row advances to `failed` with an `error_class`.

    Raises PublishError only when the call shape itself is wrong
    (missing row, invalid status); transient faults are recorded on
    the row and returned via PublishResult.published=False.
    """
    # 1. Locate the rendered_page row.
    page_row = conn.execute(
        "SELECT rendered_page_id, vault_path_placeholder, render_sha256,"
        "       page_kind, page_key, template_version"
        " FROM rendered_page WHERE rendered_page_id=?",
        (page_id,)).fetchone()
    if page_row is None:
        raise PublishError(
            f"unknown rendered_page {page_id!r}",
            error_class="unknown_page")
    _rid, _vault_ph, render_sha, page_kind, page_key, template_version = page_row

    # 2. Resolve the local render file path. The render record MUST
    # exist and its SHA must match `rendered_page.render_sha256`.
    local_path = houchen_publish_paths.render_page_path(
        template_version, page_kind, page_key)
    _publish_root_under_data_root(local_path)
    content = _read_render_file(local_path, expected_sha=render_sha)

    # 3. VaultWriter call sequence: PUT → GET → SHA. The vault_path is
    # composed by the caller (CLI); we trust it as a string here. A
    # real deployment uses `vault_path_for(page_kind, page_key, prefix)`
    # from `houchen_publish_paths`. We keep this layer ignorant of the
    # configured prefix to keep the writer-protocol testable.
    vault_path = _vault_ph
    existing = _fetch_existing_record(conn, page_id, vault_path)
    if existing is not None:
        pub_id, status, vault_sha = existing
        if status == "published":
            return PublishResult(page_id=page_id, vault_path=vault_path,
                                 published=True)
        # else: continue retry path below.

    try:
        vault_writer.put_pipeline(vault_path, content)
    except Exception as exc:
        return _record_failure(conn, page_id, vault_path, render_sha,
                               error_class="put_failed", detail=str(exc))

    try:
        fetched = vault_writer.get_pipeline(vault_path)
    except Exception as exc:
        return _record_failure(conn, page_id, vault_path, render_sha,
                               error_class="readback_failed", detail=str(exc))
    if fetched is None:
        return _record_failure(conn, page_id, vault_path, render_sha,
                               error_class="readback_missing",
                               detail="get_pipeline returned None")
    if _sha256_text(fetched) != render_sha:
        return _record_failure(conn, page_id, vault_path, render_sha,
                               error_class="readback_mismatch",
                               detail="sha256 differs from rendered_page.render_sha256")

    # 4. Success: upsert publish_record with status='published'.
    upsert_published(conn, page_id, vault_path, render_sha,
                     actor=actor)
    return PublishResult(page_id=page_id, vault_path=vault_path,
                         published=True)


def upsert_published(conn, page_id: str, vault_path: str,
                     render_sha: str, *, actor: str) -> None:
    """Insert or update the `publish_record` row to status='published'."""
    existing = _fetch_existing_record(conn, page_id, vault_path)
    if existing is None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        publish_id = f"pub_{now}_{page_id[:8]}"
        conn.execute(
            "INSERT INTO publish_record("
            "  publish_id, page_id, vault_path, vault_sha256,"
            "  status, attempted_at, published_at)"
            " VALUES (?, ?, ?, ?, 'published', ?, ?)",
            (publish_id, page_id, vault_path, render_sha, now, now))
    else:
        conn.execute(
            "UPDATE publish_record"
            " SET status='published', vault_sha256=?, published_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            " WHERE page_id=? AND vault_path=?",
            (render_sha, page_id, vault_path))
    conn.commit()


def _record_failure(conn, page_id: str, vault_path: str, render_sha: str,
                    *, error_class: str, detail: str) -> PublishResult:
    """Upsert publish_record with status='failed'; return PublishResult."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    existing = _fetch_existing_record(conn, page_id, vault_path)
    if existing is None:
        publish_id = f"pub_{now}_{page_id[:8]}"
        conn.execute(
            "INSERT INTO publish_record("
            "  publish_id, page_id, vault_path, vault_sha256,"
            "  status, error_class, detail, attempted_at)"
            " VALUES (?, ?, ?, ?, 'failed', ?, ?, ?)",
            (publish_id, page_id, vault_path, render_sha,
             error_class, detail[:512], now))
    else:
        conn.execute(
            "UPDATE publish_record"
            " SET status='failed', vault_sha256=?, error_class=?,"
            "     detail=?, attempted_at=?"
            " WHERE page_id=? AND vault_path=?",
            (render_sha, error_class, detail[:512], now,
             page_id, vault_path))
    conn.commit()
    return PublishResult(page_id=page_id, vault_path=vault_path,
                         published=False, error_class=error_class,
                         error_detail=detail[:512])


def is_published(conn, page_id: str, vault_path: str) -> bool:
    row = conn.execute(
        "SELECT status FROM publish_record"
        " WHERE page_id=? AND vault_path=?",
        (page_id, vault_path)).fetchone()
    return bool(row) and row[0] == "published"


def count_published(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM publish_record WHERE status='published'"
    ).fetchone()[0]


def count_failed(conn) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM publish_record WHERE status='failed'"
    ).fetchone()[0]


def export_obsidian_index(conn, *, out_path: str) -> None:
    """Write `<out_path>` with the rendered_page ↔ vault_path registry.

    Per-render registry used by the readback test to detect orphaned
    published pages. Idempotent; overwrites any existing file.
    """
    rows = conn.execute(
        "SELECT rp.rendered_page_id, rp.page_key, rp.template_version,"
        "       rp.render_sha256, pr.vault_path, pr.status"
        " FROM rendered_page rp"
        " LEFT JOIN publish_record pr"
        "   ON pr.page_id = rp.rendered_page_id"
        " ORDER BY rp.rendered_page_id, pr.vault_path"
    ).fetchall()
    items = [
        {"page_id": r[0], "page_key": r[1], "template_version": r[2],
         "render_sha256": r[3], "vault_path": r[4], "status": r[5]}
        for r in rows
    ]
    payload = {"pages": items, "schema_version": houchen_schema.VERSION}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)