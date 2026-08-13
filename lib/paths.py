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

# Path namespace inside the Obsidian vault (machine-owned, written via REST API)
VAULT_PIPELINE_PREFIX = "宏观经济/_pipeline"

# Ensure dirs exist on import
for _d in (CONFIG, LIB, DATA, SNAPS, LOGS, QUEUE):
    os.makedirs(_d, exist_ok=True)
