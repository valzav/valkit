import os
from pathlib import Path

from valkit.mac_apps.manifest import manifest_json, parse_manifest
from valkit.mac_apps.model import Manifest

STATE_FILE = Path.home() / ".local" / "state" / "mac-apps" / "applied.json"
"""The manifest of the last `apply` on this Mac. Never committed."""


def load_state(path: Path = STATE_FILE) -> Manifest | None:
    """The previous applied manifest, or None before the first `apply`."""
    if not path.exists():
        return None
    return parse_manifest(path.read_text())


def save_state(manifest: Manifest, path: Path = STATE_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written beside the target and renamed over it, so a crash never leaves half a file.
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(manifest_json(manifest))
    os.replace(temporary, path)
