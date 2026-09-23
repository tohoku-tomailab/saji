"""wheel を作るときに git のコミットを埋め込む（manifest.json の git_commit になる）。

`uv tool install git+<URL>` でも Web のビルド（scripts/build_web.py）でも同じ仕組みで入る。
git が使えないときは何もしない（git_commit は null になる）。
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def _git(root: str, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name != "wheel":
            return
        commit = _git(self.root, "rev-parse", "--short", "HEAD")
        if commit and _git(self.root, "status", "--porcelain", "--untracked-files=no"):
            commit += "-dirty"
        path = Path(tempfile.mkdtemp()) / "_build_info.py"
        path.write_text(f"GIT_COMMIT = {commit!r}\n", encoding="utf-8")
        build_data["force_include"][str(path)] = "saji/_build_info.py"
