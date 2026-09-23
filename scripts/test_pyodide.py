"""テストを Pyodide（ブラウザ内の Python）で実行する。

    uv run python scripts/build_web.py
    uv run --with playwright python scripts/test_pyodide.py [pytest の引数 ...]

仕組み: 一時フォルダに「テスト一式の zip・saji の wheel・小さな HTML」を置いてローカルで配信し、
ヘッドレスブラウザで開く。ページは Pyodide（web/ と同じ版）を読み込み、tests/ を展開して
pytest を実行し、結果の出力と終了コードを返す。

ブラウザは Playwright の chromium を使う（`uv run --with playwright playwright install chromium`）。
Windows で Edge を使うなら環境変数 SAJI_BROWSER_CHANNEL=msedge。
ネイティブでしか意味のないテストには `@pytest.mark.native` を付ける（ここでは除外する）。
"""

from __future__ import annotations

import functools
import http.server
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"

PAGE = """<!doctype html><meta charset="utf-8"><title>saji pyodide tests</title>
<script type="module">
const version = await (await fetch("dist/version.json")).json();
const tools = await (await fetch("dist/tools.json")).json();
const base = `https://cdn.jsdelivr.net/pyodide/v${version.pyodide_version}/full/`;
const { loadPyodide } = await import(base + "pyodide.mjs");
let out = "";
const py = await loadPyodide({ indexURL: base, stdout: (s) => { out += s + "\\n"; }, stderr: (s) => { out += s + "\\n"; } });
const vendored = version.vendored_wheels || {};
const pkgs = new Set(["pytest", "matplotlib"]);
for (const t of tools) for (const p of t.packages) if (!(p in vendored)) pkgs.add(p);
await py.loadPackage([...pkgs]);
const site = py.runPython("import site; site.getsitepackages()[0]");
for (const w of [version.saji_wheel, ...Object.values(vendored)]) {
  py.unpackArchive(await (await fetch("dist/" + w)).arrayBuffer(), "wheel", { extractDir: site });
}
py.unpackArchive(await (await fetch("tests.zip")).arrayBuffer(), "zip", { extractDir: "/home/pyodide/work" });
const args = await (await fetch("args.json")).json();
py.globals.set("ARGS", py.toPy(args));
const code = await py.runPythonAsync(`
import os, sys, pytest
os.chdir("/home/pyodide/work")
sys.path.insert(0, "/home/pyodide/work")
paths = [] if any(not a.startswith("-") for a in ARGS) else ["tests"]
int(pytest.main(["-q", "-p", "no:cacheprovider", "-m", "not native",
                 "-W", "ignore::DeprecationWarning", *ARGS, *paths]))
`);
window.__result = { code, out };
</script>"""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not (DIST / "version.json").exists():
        print("web/dist がありません。先に scripts/build_web.py を実行してください。", file=sys.stderr)
        return 2
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp)
        shutil.copytree(DIST, site / "dist")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for f in (ROOT / "tests").rglob("*"):
                if f.is_file() and "__pycache__" not in f.parts:
                    zf.write(f, f.relative_to(ROOT).as_posix())
            zf.writestr("pyproject.toml", (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        (site / "tests.zip").write_bytes(buf.getvalue())
        (site / "args.json").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
        (site / "index.html").write_text(PAGE, encoding="utf-8")

        handler = functools.partial(QuietHandler, directory=str(site))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}/"
        try:
            with sync_playwright() as p:
                channel = os.environ.get("SAJI_BROWSER_CHANNEL") or None
                browser = p.chromium.launch(channel=channel, headless=True)
                page = browser.new_page()
                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(url)
                page.wait_for_function("window.__result !== undefined || false", timeout=900_000,
                                       polling=1000)
                result = page.evaluate("window.__result")
                browser.close()
        finally:
            server.shutdown()
    print(result["out"])
    for e in errors:
        print("pageerror:", e, file=sys.stderr)
    return int(result["code"])


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    sys.exit(main())
