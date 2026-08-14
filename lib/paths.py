"""Central path constants for the macro-pipeline."""
import os

ROOT = os.path.expanduser("~/macro-pipeline")
CONFIG = os.path.join(ROOT, "config")
LIB = os.path.join(ROOT, "lib")
DATA = os.path.join(ROOT, "data")
SNAPS = os.path.join(DATA, "snapshots")
LOGS = os.path.join(ROOT, "logs")
QUEUE = os.path.join(ROOT, "queue")

STORE_DB = os.path.join(DATA, "store.db")
STATE_JSON = os.path.join(DATA, "state.json")
SOURCES_YAML = os.path.join(CONFIG, "sources.yaml")
REST_ENV = os.path.join(CONFIG, "rest.env")
INSIGHT_ENV = os.path.join(CONFIG, "insight.env")
INSIGHT_ENV_EXAMPLE = os.path.join(CONFIG, "insight.env.example")
INSIGHT_PROMPT = os.path.join(CONFIG, "insight_prompt.md")
INSIGHT_SCHEMA = os.path.join(CONFIG, "insight_schema.json")
INSIGHT_DIR = os.path.join(DATA, "insights")
INSIGHT_FACTS = os.path.join(INSIGHT_DIR, "facts")
INSIGHT_RESPONSES = os.path.join(INSIGHT_DIR, "responses")
INSIGHT_ARTIFACTS = os.path.join(INSIGHT_DIR, "artifacts")
INSIGHT_SPOOL = os.path.join(INSIGHT_DIR, "spool")

# Path namespace inside the Obsidian vault (machine-owned, written via REST API)
VAULT_PIPELINE_PREFIX = "宏观经济/_pipeline"

# Ensure dirs exist on import. Insight dirs hold model responses / fact packs
# (pre-publication content): create them 0o700 and tighten any pre-existing
# copy — os.makedirs(mode=...) never tightens an already-existing directory.
for _d in (CONFIG, LIB, DATA, SNAPS, LOGS, QUEUE):
    os.makedirs(_d, exist_ok=True)
for _d in (INSIGHT_DIR, INSIGHT_FACTS, INSIGHT_RESPONSES, INSIGHT_ARTIFACTS,
           INSIGHT_SPOOL):
    os.makedirs(_d, mode=0o700, exist_ok=True)
    try:
        os.chmod(_d, 0o700)
    except OSError:
        pass
