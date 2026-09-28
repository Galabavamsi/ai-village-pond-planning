"""Deployment settings read from the environment or a git-ignored ``.env`` file.

Secrets such as the Google Maps key never live in the repository. Put
``GOOGLE_MAPS_API_KEY=...`` in ``.env`` at the repository root (it is listed in
``.gitignore``) or export it before starting the server.
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Set ``KEY=VALUE`` lines as environment defaults; real variables win."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def google_maps_key() -> str | None:
    """Browser key for Google Maps Platform, or None when Google layers are off."""
    return os.environ.get("GOOGLE_MAPS_API_KEY", "").strip() or None
