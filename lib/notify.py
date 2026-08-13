"""macOS notification via osascript. Best-effort, never raises."""
import subprocess


def _escape(s: str) -> str:
    # osascript string safety: escape double quotes and backslashes
    return s.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, body: str) -> None:
    """Send a macOS notification. Swallows all errors (notification is best-effort)."""
    try:
        script = (
            f'display notification "{_escape(body)}" '
            f'with title "{_escape(title)}" sound name "Glass"'
        )
        subprocess.run(["osascript", "-e", script], check=False, timeout=10)
    except Exception:
        pass
