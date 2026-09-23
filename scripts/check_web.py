"""Web 版で1つのツールを実際に動かして確かめる（ヘッドレスブラウザ。ツールを足したときの確認用）。

    uv run python scripts/build_web.py
    uv run --with playwright python scripts/check_web.py <tool> <入力名>=<ファイル>[;<ファイル>...] \
        [<入力名>=...] [--param <名前>=<値> ...] [--out <保存先フォルダ>]

例:
    uv run --with playwright python scripts/check_web.py xrd-process \
        "raw=tests/fixtures/xrd/synthA.TXT" "peaks=tests/fixtures/xrd/peaks.json" --param norm=max

web/ をローカルで配信してページを開き、ファイルを選んでパラメータを入れ、実行して、
結果のメッセージ・zip・スクリーンショット（フォーム・結果・スマートフォン幅）を保存する。
エラーの表示・ページのエラーがあれば終了コード 1。
ブラウザは Playwright の chromium（初回は `uv run --with playwright playwright install chromium`）。
Windows で Edge を使うなら環境変数 SAJI_BROWSER_CHANNEL=msedge。
"""

from __future__ import annotations

import argparse
import functools
import http.server
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tool")
    ap.add_argument("inputs", nargs="*", help="<入力名>=<ファイル>[;<ファイル>...]")
    ap.add_argument("--param", action="append", default=[], help="<名前>=<値>（フォームに入れる値）")
    ap.add_argument("--out", default=None, help="zip とスクリーンショットの保存先（既定は一時フォルダ）")
    args = ap.parse_args()
    if not (ROOT / "web" / "dist" / "tools.json").exists():
        print("web/dist がありません。先に scripts/build_web.py を実行してください。", file=sys.stderr)
        return 2
    out = Path(args.out or tempfile.mkdtemp(prefix="saji-web-"))
    out.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright

    handler = functools.partial(QuietHandler, directory=str(ROOT / "web"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    errors: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get("SAJI_BROWSER_CHANNEL") or None, headless=True)
            page = browser.new_page(viewport={"width": 1400, "height": 1000}, accept_downloads=True)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            t0 = time.time()
            page.goto(f"http://127.0.0.1:{server.server_port}/#{args.tool}")
            page.wait_for_selector('#engine[data-state="ready"]', timeout=300_000)
            print(f"準備完了まで {time.time() - t0:.1f} 秒")

            for spec in args.inputs:
                name, paths = spec.split("=", 1)
                picker = f'#inputs fieldset:has(#files-{name}) input[type=file]:not([webkitdirectory])'
                page.set_input_files(picker, [str(ROOT / p) for p in paths.split(";")])
            for kv in args.param:
                name, value = kv.split("=", 1)
                field = page.locator(f'.field[data-param="{name}"]')
                el = field.locator("input, select, textarea").first
                tag = el.evaluate("e => e.tagName")
                if tag == "SELECT":
                    el.select_option(value)
                elif el.get_attribute("type") == "checkbox":
                    el.set_checked(value.lower() in ("1", "true", "yes", "on"))
                else:
                    el.fill(value)
            page.screenshot(path=str(out / f"{args.tool}-form.png"), full_page=True)

            t1 = time.time()
            page.click("#run")
            page.wait_for_selector("#result:not([hidden])", timeout=600_000)
            page.wait_for_timeout(1000)
            print(f"実行 {time.time() - t1:.1f} 秒")
            messages = page.inner_text("#messages")
            print(messages)
            if page.locator(".msg.err").count():
                errors.append("エラーが表示されました")
            if page.is_visible("#download"):
                with page.expect_download() as d:
                    page.click("#download")
                d.value.save_as(str(out / d.value.suggested_filename))
                print("zip:", out / d.value.suggested_filename)
            page.screenshot(path=str(out / f"{args.tool}-result.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 900})
            page.screenshot(path=str(out / f"{args.tool}-mobile.png"))
            browser.close()
    finally:
        server.shutdown()
    print("スクリーンショット:", out)
    for e in errors:
        print(e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
