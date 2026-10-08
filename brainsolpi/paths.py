from __future__ import annotations

import os
import sys
from pathlib import Path

APP = "brainsolpi"
HEX_NAME = "brainsol_bridge.hex"


def _home() -> Path:
    return Path.home()


def config_dir() -> Path:
    # same places platformdirs would pick, without the extra dependency
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(_home() / "AppData" / "Roaming")
        return Path(base) / APP
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / APP
    base = os.environ.get("XDG_CONFIG_HOME") or str(_home() / ".config")
    return Path(base) / APP


def data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(_home() / "AppData" / "Local")
        return Path(base) / APP
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / APP
    base = os.environ.get("XDG_DATA_HOME") or str(_home() / ".local" / "share")
    return Path(base) / APP


def repo_root() -> Path | None:
    # the pi uses an editable install, so the package sits inside the repo
    root = Path(__file__).resolve().parent.parent
    if (root / "pyproject.toml").is_file():
        return root
    return None


def default_hex() -> Path | None:
    root = repo_root()
    if root is None:
        return None
    return root / "firmware" / HEX_NAME


def default_web() -> Path | None:
    root = repo_root()
    if root is None:
        return None
    for cand in (root / "web", root.parent / "web"):
        if (cand / "index.html").is_file():
            return cand
    return None
