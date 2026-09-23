"""Web 版のビルド（npm やバンドラは使わない）。

    uv run python scripts/build_web.py

web/dist/ に次を書き出す（web/dist は .gitignore 対象）:
  wheels/saji-<版>-py3-none-any.whl   … Python パッケージ（ビルド情報を埋め込む）
  wheels/<同梱する依存>.whl            … Pyodide に入っていない純 Python の依存
  tools.json                           … 全ツールの TOOL 定義（フォームの元）
  version.json                         … 版・git コミット・Pyodide の版・wheel の一覧

確認は `uv run python -m http.server -d web 8000` で http://localhost:8000/ を開く。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
DIST = WEB / "dist"
WHEELS = DIST / "wheels"

# Pyodide の版（docs/maintenance.md の年次更新で上げる）。CLI 側の依存の版もこれに合わせる。
PYODIDE_VERSION = "314.0.7"

# Pyodide に同梱されていない純 Python の依存。ビルド時に wheel を取ってきて一緒に配る
# （実行時に PyPI へ取りに行かないため）。ツールの packages にこの名前を書けば読み込まれる。
VENDORED = ["pybaselines"]


def run(cmd: list[str]) -> str:
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        sys.stderr.write(out.stdout + out.stderr)
        raise SystemExit(f"失敗: {' '.join(cmd)}")
    return out.stdout.strip()


def git_commit() -> str | None:
    try:
        commit = run(["git", "rev-parse", "--short", "HEAD"])
        dirty = run(["git", "status", "--porcelain", "--untracked-files=no"])
        return commit + ("-dirty" if dirty else "")
    except SystemExit:
        return None


def build_saji_wheel(commit: str | None) -> Path:
    run(["uv", "build", "--wheel", "--out-dir", str(WHEELS)])
    wheel = next(WHEELS.glob("saji-*.whl"))
    # ビルド情報を埋め込む（manifest.json の git_commit になる）。ソースツリーには書かない。
    with zipfile.ZipFile(wheel, "a") as zf:
        zf.writestr("saji/_build_info.py", f"GIT_COMMIT = {commit!r}\n")
    return wheel


def fetch_vendored() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in VENDORED:
        version = metadata.version(name)
        run(["uv", "run", "--with", "pip", "python", "-m", "pip", "download", "--quiet",
             f"{name}=={version}", "--no-deps", "--only-binary=:all:", "-d", str(WHEELS)])
        wheel = next(WHEELS.glob(f"{name.replace('-', '_')}-{version}-*.whl"))
        if not wheel.name.endswith("-none-any.whl"):
            raise SystemExit(f"{wheel.name} は純 Python の wheel ではありません（Pyodide で動きません）")
        out[name] = f"wheels/{wheel.name}"
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, str(ROOT / "src"))
    from saji import __version__, registry

    if DIST.exists():
        shutil.rmtree(DIST)
    WHEELS.mkdir(parents=True)

    commit = git_commit()
    wheel = build_saji_wheel(commit)
    vendored = fetch_vendored()

    tools = registry.tools_json()
    for t in tools:
        t["panel"] = (WEB / "panels" / f"{t['name']}.js").exists()
    (DIST / "tools.json").write_text(json.dumps(tools, ensure_ascii=False, indent=1), encoding="utf-8")
    version = {
        "version": __version__,
        "git_commit": commit,
        "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pyodide_version": PYODIDE_VERSION,
        "saji_wheel": f"wheels/{wheel.name}",
        "vendored_wheels": vendored,
    }
    (DIST / "version.json").write_text(json.dumps(version, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"web/dist を作りました: saji {__version__} ({commit}) / ツール {len(tools)} 個 / "
          f"Pyodide {PYODIDE_VERSION}")


if __name__ == "__main__":
    main()
