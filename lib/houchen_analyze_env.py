"""Houchen analyze provider env (audit F-6).

Reads `config/houchen_analyze.env` only — never `config/insight.env`.
Delegates parsing to `insight_provider.load_config` so provider HTTP
semantics stay aligned with the macro stack without sharing secrets files.
"""
from __future__ import annotations

import os


def analyze_env_path() -> str:
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo, "config", "houchen_analyze.env")


def load_provider_config(provider: str):
    """Load `ProviderConfig` for `provider` from houchen analyze env.

    The env file's `INSIGHT_PROVIDER` must match the CLI `--provider`
  value (anthropic / deepseek / minimax).
    """
    import insight_provider

    path = analyze_env_path()
    if not os.path.isfile(path):
        raise insight_provider.ConfigurationError(
            f"houchen analyze env missing: {path}",
            error_class="missing_config",
        )
    cfg = insight_provider.load_config(path)
    if cfg.provider != provider:
        raise insight_provider.ConfigurationError(
            f"env INSIGHT_PROVIDER={cfg.provider!r} != CLI --provider={provider!r}",
            error_class="provider_mismatch",
        )
    return cfg
