"""Web 版のフォームの動作を確かめる（設定の保存・復元・既定値に戻す・書き出し・読み込み）。

    uv run python scripts/build_web.py
    uv run --with playwright python scripts/test_web_form.py

web/ をローカルで配信してヘッドレスブラウザで開き、xrd-overlay-2 のフォームを操作する。
Python（Pyodide）の準備は待たない（フォームだけを見る）。失敗があれば終了コード 1。
ブラウザは Playwright の chromium。Windows で Edge を使うなら環境変数 SAJI_BROWSER_CHANNEL=msedge。
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = "xrd-overlay-2"
KEY = f"saji:params:{TOOL}"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


class QuietServer(http.server.ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:
        if not isinstance(sys.exc_info()[1], ConnectionError):   # 読み込み直しで切れた転送は無視
            super().handle_error(request, client_address)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not (ROOT / "web" / "dist" / "tools.json").exists():
        print("web/dist がありません。先に scripts/build_web.py を実行してください。", file=sys.stderr)
        return 2
    from playwright.sync_api import sync_playwright

    handler = functools.partial(QuietHandler, directory=str(ROOT / "web"))
    server = QuietServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/#{TOOL}"
    failures: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="saji-form-"))

    def check(cond: bool, what: str) -> None:
        print(("ok  " if cond else "NG  ") + what)
        if not cond:
            failures.append(what)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=os.environ.get("SAJI_BROWSER_CHANNEL") or None, headless=True)
            page = browser.new_page(accept_downloads=True)
            page.on("pageerror", lambda e: failures.append(f"pageerror: {e}"))

            def field(name: str):
                return page.locator(f'.field[data-param="{name}"]')

            def value(name: str) -> str:
                return field(name).locator("input, select, textarea").first.input_value()

            def open_tool() -> None:   # 読み込み直す（同じ URL への goto では読み込み直さない）
                if page.url == url:
                    page.reload()
                else:
                    page.goto(url)
                page.wait_for_selector('.field[data-param="gap"]')

            def stored() -> dict | None:
                s = page.evaluate(f"localStorage.getItem({json.dumps(KEY)})")
                return json.loads(s)["values"] if s else None

            open_tool()
            page.evaluate("localStorage.clear()")
            open_tool()
            check(page.locator(".field.changed").count() == 0, "初めて開いたときは印なし")
            check(page.is_disabled("#param-reset"), "変えていなければ「既定値に戻す」は押せない")

            # 変えると保存され、開き直すと戻る
            default_gap = value("gap")
            field("gap").locator("input").fill("0.5")
            field("legend").locator("select").select_option("outside")
            field("xlim").locator("input").nth(0).fill("30")
            field("xlim").locator("input").nth(1).fill("80")
            field("bottom_up").locator("input").check()
            page.click("details.advanced > summary")
            field("traces").locator("textarea").fill('[{"file": "a.xy", "label": "A"}]')
            s = stored()
            check(s == {"gap": "0.5", "legend": "outside", "xlim": ["30", "80"], "bottom_up": True,
                        "traces": '[{"file": "a.xy", "label": "A"}]'}, f"変えた欄だけ保存: {s}")
            check(field("gap").get_attribute("class").split().count("changed") == 1, "変えた欄に印")
            open_tool()
            check(value("gap") == "0.5" and value("legend") == "outside", "開き直すと値が戻る")
            check(field("xlim").locator("input").nth(1).input_value() == "80", "range も戻る")
            check(field("bottom_up").locator("input").is_checked(), "チェックボックスも戻る")
            check(page.locator("details.advanced").get_attribute("open") is not None, "詳細設定を変えていれば開く")
            check("変更 1" in page.inner_text("details.advanced > summary"), "詳細設定の見出しに変更数")
            check("前回の設定を復元" in page.inner_text("#param-note"), "復元したことを表示")

            # 使えない保存値は捨てる
            page.evaluate(f"""localStorage.setItem({json.dumps(KEY)}, JSON.stringify({{v: 1, values: {{
                legend: "bogus", gap: "abc", ref_height: "0.3", removed_param: 1}}}}))""")
            open_tool()
            check(value("legend") == "inside" and value("gap") == default_gap, "使えない値は既定値")
            check(value("ref_height") == "0.3", "使える値は戻る")
            note = page.inner_text("#param-note")
            check("removed_param" in note and "legend" in note, f"捨てた項目を表示: {note}")
            check(stored() == {"ref_height": "0.3"}, "捨てた値は保存からも消す")

            # 既定値に戻す → 元に戻す
            page.click("#param-reset")
            check(value("ref_height") != "0.3" and stored() is None, "既定値に戻すと保存も消える")
            page.click("#param-note .linkbtn")
            check(value("ref_height") == "0.3" and stored() == {"ref_height": "0.3"}, "元に戻す")

            # 書き出し（CLI の --params と同じ形）
            field("xlim").locator("input").nth(0).fill("25")
            field("xlim").locator("input").nth(1).fill("85")
            with page.expect_download() as d:
                page.click("#param-export")
            out = tmp / d.value.suggested_filename
            d.value.save_as(str(out))
            data = json.loads(out.read_text(encoding="utf-8"))
            check(data["tool"] == TOOL and data["params"]["xlim"] == [25, 85]
                  and data["params"]["ref_height"] == 0.3, f"書き出し: {data}")

            # 読み込み（manifest.json の形。無い項目は既定値、合わない値・無い項目は表示）
            manifest = tmp / "manifest.json"
            manifest.write_text(json.dumps({"tool": "xrd-overlay", "params": {
                "gap": 0.8, "xlim": [None, 70], "legend": "none", "traces": [{"file": "b.xy"}],
                "cmap": "nope", "peaks_on": "each"}}), encoding="utf-8")
            page.set_input_files("#param-import-file", str(manifest))
            page.wait_for_function("document.querySelector('#param-note').textContent.includes('読み込み')")
            check(value("gap") == "0.8" and value("legend") == "none", "読み込んだ値が入る")
            check(field("xlim").locator("input").nth(0).input_value() == ""
                  and field("xlim").locator("input").nth(1).input_value() == "70", "range の null は空欄")
            check(value("ref_height") != "0.3", "ファイルに無い項目は既定値")
            check(json.loads(value("traces")) == [{"file": "b.xy"}], "json の値は整形して入る")
            note = page.inner_text("#param-note")
            check("xrd-overlay の設定" in note and "cmap" in note and "peaks_on" in note, f"読み込みの表示: {note}")
            check(stored().get("gap") == "0.8", "読み込んだ値も保存")

            # 別のツールには影響しない
            page.goto(url.replace(TOOL, "xrd-overlay"))
            page.wait_for_selector('.field[data-param="gap"]')
            check(value("gap") == default_gap, "ツールごとに別に保存")

            # 保存できない環境でも動く
            ctx = browser.new_context()
            ctx.add_init_script("Object.defineProperty(window, 'localStorage', {get() { throw new Error('denied'); }})")
            page2 = ctx.new_page()
            page2.on("pageerror", lambda e: failures.append(f"pageerror (storage 不可): {e}"))
            page2.goto(url)
            page2.wait_for_selector('.field[data-param="gap"]')
            page2.locator('.field[data-param="gap"] input').fill("0.7")
            check(page2.locator('.field[data-param="gap"]').get_attribute("class").split().count("changed") == 1,
                  "localStorage が使えなくても印は付く")
            browser.close()
    finally:
        server.shutdown()
    for f in failures:
        print(f, file=sys.stderr)
    print("失敗なし" if not failures else f"失敗 {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
