"""Obsidian Local REST API client + vault write helpers.

Writes ONLY to the machine-owned namespace 宏观经济/_pipeline/ (never touches
hand-curated notes). The REST API runs through the Obsidian app, so this
bypasses the macOS TCC restriction that blocks direct filesystem writes.
"""
import urllib3
import urllib.parse
import requests
import paths

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _load_rest_config() -> dict:
    cfg = {}
    with open(paths.REST_ENV, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip()
    if "OBSIDIAN_TOKEN" not in cfg:
        raise RuntimeError("OBSIDIAN_TOKEN missing from config/rest.env")
    return cfg


class VaultWriter:
    def __init__(self):
        c = _load_rest_config()
        self.token = c["OBSIDIAN_TOKEN"]
        self.port = c.get("OBSIDIAN_PORT", "27124")
        self.base = f"https://127.0.0.1:{self.port}"

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def _url(self, vault_path: str) -> str:
        return f"{self.base}/vault/{urllib.parse.quote(vault_path)}"

    # --- low-level transport ---
    def get(self, vault_path: str):
        r = requests.get(self._url(vault_path), headers=self._headers(),
                         verify=False, timeout=20)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text

    def put(self, vault_path: str, content: str) -> int:
        r = requests.put(
            self._url(vault_path),
            headers={**self._headers(), "Content-Type": "text/markdown"},
            data=content.encode("utf-8"),
            verify=False,
            timeout=20,
        )
        r.raise_for_status()
        return r.status_code

    # --- pipeline-namespace helpers (all under 宏观经济/_pipeline/) ---
    def put_pipeline(self, rel_path: str, content: str) -> int:
        return self.put(f"{paths.VAULT_PIPELINE_PREFIX}/{rel_path}", content)

    def get_pipeline(self, rel_path: str):
        return self.get(f"{paths.VAULT_PIPELINE_PREFIX}/{rel_path}")

    def append_pipeline(self, rel_path: str, addition: str) -> int:
        """Append `addition` to a pipeline note (GET + concat + PUT)."""
        existing = self.get_pipeline(rel_path) or ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        return self.put_pipeline(rel_path, existing + addition)
