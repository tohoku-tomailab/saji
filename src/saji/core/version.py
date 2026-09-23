"""バージョンと git コミットの取得（manifest.json に記録する）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .. import __version__


def package_version() -> str:
    return __version__


def is_pyodide() -> bool:
    return sys.platform == "emscripten"


def pyodide_version() -> str | None:
    if not is_pyodide():
        return None
    try:
        import pyodide  # type: ignore[import-not-found]
        return str(pyodide.__version__)
    except Exception:  # noqa: BLE001
        return None


def git_commit() -> str | None:
    """ビルド時に埋め込んだコミット（_build_info.py）、無ければ作業ツリーの HEAD。"""
    try:
        from .._build_info import GIT_COMMIT  # type: ignore[import-not-found]
        return GIT_COMMIT
    except ImportError:
        pass
    if is_pyodide():
        return None
    repo = Path(__file__).resolve().parents[3]
    if not (repo / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo,
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None
