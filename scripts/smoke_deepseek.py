"""Smoke-test the configured insight provider against the live API.

Confirms transport + auth + JSON parsing ONLY. Does NOT touch the ledger,
artifacts, or vault — safe to re-run any number of times. Uses a trivial
prompt/schema so it exercises the wire path without depending on the real
insight prompt/schema files.

Usage:  python3 scripts/smoke_deepseek.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))

import insight_provider


def main():
    cfg = insight_provider.load_config()
    print(f"provider={cfg.provider} model={cfg.model} base_url={cfg.base_url}")
    provider = insight_provider.build_provider(cfg)

    # Trivial fact pack + schema: we only want to prove the API is reachable,
    # authenticated, and returns a JSON object we can parse.
    fact_pack = {
        "smoke": True,
        "note": "connectivity check, not a real macro release",
        "value": 42,
    }
    prompt = (
        "Return a JSON object with two keys: 'ok' (boolean true) and "
        "'echo' (echo back the number in the input). Output JSON only."
    )
    schema = {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "echo": {"type": "number"},
        },
        "required": ["ok", "echo"],
        "additionalProperties": False,
    }

    result = provider.generate(fact_pack, prompt=prompt, schema=schema)
    print("parsed:", result)
    if not isinstance(result, dict):
        raise SystemExit("FAIL: provider did not return a JSON object")
    if "ok" not in result or "echo" not in result:
        raise SystemExit("FAIL: missing expected keys 'ok'/'echo'")
    print("SMOKE OK — provider reachable, authenticated, JSON parsed")


if __name__ == "__main__":
    main()
