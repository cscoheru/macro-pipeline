"""PR-4 Phase 1 — FakeVaultWriter fixture.

A test double for the `VaultWriter` protocol used by
`houchen_publisher`. Records every PUT and lets tests inject failure
modes:

  - `simulate_put_error`: the next put_pipeline call raises
    `RuntimeError('simulated PUT failure')`
  - `simulate_get_returns_none`: the next get_pipeline call returns None
  - `simulate_get_sha_mismatch`: the next get_pipeline call returns text
    whose SHA does NOT match the corresponding put_sha256 (i.e. simulates
    a vault that returns different bytes than what was PUT)
  - `simulate_get_error`: the next get_pipeline call raises

These are one-shot (consumed on the next call). The fixture tracks the
last PUT sha256 so the mismatch simulation is realistic.
"""
from __future__ import annotations

import hashlib
from typing import Optional


class FakeVaultWriter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []  # (op, path, sha)
        self._stored: dict[str, str] = {}             # path -> content
        self._simulate_put_error = False
        self._simulate_get_error = False
        self._simulate_get_returns_none = False
        self._simulate_get_sha_mismatch = False
        self._last_put_sha: dict[str, str] = {}       # path -> last put sha

    def put_pipeline(self, vault_path: str, content: str) -> None:
        self.calls.append(("put", vault_path, _sha256(content)))
        if self._simulate_put_error:
            self._simulate_put_error = False
            raise RuntimeError("simulated PUT failure")
        sha = _sha256(content)
        self._stored[vault_path] = content
        self._last_put_sha[vault_path] = sha

    def get_pipeline(self, vault_path: str) -> Optional[str]:
        self.calls.append(("get", vault_path, ""))
        if self._simulate_get_error:
            self._simulate_get_error = False
            raise RuntimeError("simulated GET failure")
        if self._simulate_get_returns_none:
            self._simulate_get_returns_none = False
            return None
        if self._simulate_get_sha_mismatch and vault_path in self._stored:
            self._simulate_get_sha_mismatch = False
            # Return a string that hashes to something else.
            original = self._stored[vault_path]
            return original + "\n\n<!-- tamper -->\n"
        return self._stored.get(vault_path)

    # --- Injection helpers ---

    def simulate_put_error(self) -> None:
        self._simulate_put_error = True

    def simulate_get_error(self) -> None:
        self._simulate_get_error = True

    def simulate_get_returns_none(self) -> None:
        self._simulate_get_returns_none = True

    def simulate_get_sha_mismatch(self) -> None:
        self._simulate_get_sha_mismatch = True

    def last_put_sha(self, vault_path: str) -> Optional[str]:
        return self._last_put_sha.get(vault_path)

    def stored_content(self, vault_path: str) -> Optional[str]:
        return self._stored.get(vault_path)

    def reset(self) -> None:
        self.calls.clear()
        self._stored.clear()
        self._simulate_put_error = False
        self._simulate_get_error = False
        self._simulate_get_returns_none = False
        self._simulate_get_sha_mismatch = False
        self._last_put_sha.clear()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()