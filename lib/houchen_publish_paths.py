"""PR-4 Phase 1 — Obsidian publish path resolution (brief §11).

The publish side of the research corpus lives at `<data_root>/publish/`.
Layout:

  publish_root()/render/<template_version>/<page_kind>/<page_key>.md
  publish_root>/published/<vault_path>.sha256
  publish_root>/obsidian_index.json
  publish_root>/env_path                  — absolute path to the publish env file

Every path goes through `houchen_paths.resolve_data_root()` so the
"no symlink ancestors" + "no overlap with macro protected roots"
contract from PR-1 is preserved.

The `houchen_publish.env` file lives at the repository root (NOT under
the data root) so a user with a custom data root on a different
filesystem still configures the env file via the repo. The env file
must exist (mode 0600) for the `publish` CLI to do anything besides
dry-run; a missing env file exits 2 with a remediation message.

This module NEVER imports `lib/insight_publisher.py` or reads/writes
`data/store.db`. The PR-4 S-4 audit guard test (`scripts/test_houchen_
macro_isolation.py`) enforces the rule with a grep; see
`docs/plans/pr4-obsidian-research-map.md` §11.4.
"""
from __future__ import annotations

import os
import re

import houchen_paths


# Default Obsidian vault prefix for the research library. Configurable via
# HOUCHEN_PUBLISH_VAULT_PREFIX in the env file.
DEFAULT_VAULT_PREFIX = "Research/世界苦茶/"


def publish_root() -> str:
    """`<data_root>/publish/` — root for rendered + published files."""
    return os.path.join(houchen_paths.resolve_data_root(), "publish")


def render_dir() -> str:
    return os.path.join(publish_root(), "render")


def render_version_dir(template_version: str) -> str:
    """`<publish_root>/render/<template_version>/` — template-versioned."""
    _require_safe_version(template_version)
    return os.path.join(render_dir(), template_version)


def render_page_path(template_version: str, page_kind: str,
                     page_key: str, suffix: str = ".md") -> str:
    """`<publish_root>/render/<tv>/<page_kind>/<page_key><suffix>`.

    `page_kind` must be in the v4 `page_kind` CHECK set; `page_key` is
    restricted to the same identifier grammar used in PR-3
    (`[A-Za-z0-9_.-]+`).
    """
    _require_safe_version(template_version)
    if page_kind not in (
        "video", "concept", "claim", "forecast", "review_queue", "coverage"
    ):
        raise ValueError(f"invalid page_kind: {page_kind!r}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", page_key) or ".." in page_key:
        raise ValueError(f"invalid page_key: {page_key!r}")
    if suffix not in (".md", ".json"):
        raise ValueError(f"invalid suffix: {suffix!r}")
    return os.path.join(render_version_dir(template_version), page_kind,
                        f"{page_key}{suffix}")


def published_dir() -> str:
    """`<publish_root>/published/` — registry of vault paths + sha256."""
    return os.path.join(publish_root(), "published")


def obsidian_index_path() -> str:
    """`<publish_root>/obsidian_index.json` — per-render page registry."""
    return os.path.join(publish_root(), "obsidian_index.json")


def env_path() -> str:
    """Absolute path to `config/houchen_publish.env` (mode 0600).

    Lives in the repo, NOT under the data root, so a user with a custom
    data root on a different filesystem still configures the env via the
    repo. Missing file → `publish` CLI exits 2 with remediation; see
    `scripts/houchen_pipeline.py:cmd_publish`.
    """
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo, "config", "houchen_publish.env")


def vault_path_for(page_kind: str, page_key: str, vault_prefix: str) -> str:
    """Compose the vault path that `houchen_publisher` PUTs into Obsidian.

    The prefix is restricted to a CJK + ASCII safe-character set so a
    user-defined prefix cannot break out of the configured research
    area. Empty prefix is rejected to avoid landing pages at the vault
    root. `..` and `//` are also rejected to prevent path traversal in
    any downstream Obsidian plugin that interprets the prefix as a
    relative path.
    """
    if not vault_prefix:
        raise ValueError("vault_prefix must be non-empty")
    if not re.match(r"^[A-Za-z0-9_/.一-鿿\-]+$", vault_prefix):
        raise ValueError(f"invalid vault_prefix: {vault_prefix!r}")
    if ".." in vault_prefix:
        raise ValueError(f"vault_prefix contains '..': {vault_prefix!r}")
    if "//" in vault_prefix:
        raise ValueError(f"vault_prefix contains '//': {vault_prefix!r}")
    if not vault_prefix.endswith("/"):
        vault_prefix = vault_prefix + "/"
    return f"{vault_prefix}{page_kind}/{page_key}.md"


def _require_safe_version(version: str) -> None:
    """Same allowlist as `houchen_paths._require_safe_version`."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version) or ".." in version \
            or "/" in version or "\\" in version:
        raise ValueError(f"invalid template_version: {version!r}")