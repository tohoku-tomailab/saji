# ツールの追加手順

見本は `src/saji/tools/xrd_process.py`（ツール定義）と `src/saji/techniques/xrd.py`（手法の知識）。

## チェックリスト

1. [ ] **CLI 専用にするか決める**（`docs/design.md` の判断基準）。CLI 専用なら `web=False` と
   `cli_only_reason` を書き、理由を `docs/decisions/` に記録する。
2. [ ] **手法の知識を `techniques/<手法>.py` に書く**（読み込み・数値処理・図の組み立て）。
   同じ手法のモジュールが既にあれば足す。大きくなったら `techniques/<手法>/` のパッケージにする（例 xps）。
   特定の手法に属さない汎用のツール（CSV の結合など）は、内容を表す名前で `techniques/<名前>.py` を作る。
   入力は bytes / 文字列で受け取る（ファイルパスを受け取らない）。文字コードの判定・列名での列探しは
   `core/tableio.py` を使う（`decode_text`、`resolve_columns`、`find_header_row`、`load_named_table`（pandas が要る））。
3. [ ] **`tools/<ツール名>.py` に `TOOL` と `run()` を書く**。ファイル名はツール名の `-` を `_` にしたもの。
   - `TOOL = Tool(name=..., summary=..., description=..., inputs=[FileInput(...)], params=[Param(...)], packages=[...], plots=..., examples=[...])`
   - 入力の1つ目は CLI の位置引数になる。2つ目以降は `--<名前>` になる。
   - パラメータの型は int / float / str / bool / choice（`choices=`）/ `"range"` / `"json"`（例外）。
     `default=None` は「未指定なら使わない」。表示名 `label`・単位 `unit`・見出し `group`・
     詳細設定に畳む `advanced` を付ける。図を出すなら `STYLE_PARAM` を入れ、`plots=True` にする。
   - `packages` には Pyodide で読み込むパッケージを書く（numpy / scipy / pandas など）。
     Pyodide に無い純 Python の依存は `scripts/build_web.py` の `VENDORED` にも足す。
4. [ ] **`run(inputs, params) -> Result` の約束を守る**
   - ファイルシステムに触れない。`print` しない。ネットワークに接続しない。決定的にする。
   - 出力は `result.add_file(相対パス, bytes か str)`、図は `result.add_figure(名前, 図)`。
   - `result.log()` は経過や結果の要約（件数・使った値など）。`result.warn()` は**利用者が確かめるべきこと**
     （結果が想定と違うかもしれない・入力の一部を飛ばした・既定の扱いにした など）。Web では警告が目立つので乱用しない。
   - 機械可読の数値は `result.data`（CLI の `--json` と Web の結果に入る）。
   - 利用者が直せる入力の誤りは `InputError` を投げる（CLI の終了コード 2）。1ファイルだけ読めないときは
     警告して続け、1つも処理できなければ InputError にする。
   - 複数ファイルの入力は、渡された順（CLI はフォルダならファイル名順、Web は選んだ順を名前順に並べる）で扱う。
     順番に意味があるツールは、それを description に書く。
   - 出力する CSV は、特に理由がなければ **UTF-8（BOM 付き、Excel で開けるように）・改行 LF**。
     既存ツールから移植するときは既存の形式を保つ。
   - 図の文字は英語（Arial）。データ由来の文字（列名・ファイル名）を軸名や凡例に使うときは、
     `core.plot.checks.non_arial_texts` で確かめ、日本語なら英語の既定に落とすか、利用者が変えられるようにする。
5. [ ] **`registry.py` の `TOOL_MODULES` に1行足す**。
6. [ ] **合成データを `tests/fixtures/<手法>/` に置く**。生成スクリプト `tests/fixtures/<手法>/make.py`
   （決定的に。乱数は seed 固定）で作り、生成物もコミットする。装置の癖（文字コード・前置きの行・空欄・
   列名の揺れ）を再現したものを用意する。**実データや、実データを加工したものは置かない**。
7. [ ] **ゴールデンテストを書く**（`tests/test_<ツール>.py`、期待される出力は `tests/golden/<ツール>/`）。
   - ツールはテストから `saji.core.runner.execute(registry.get("<ツール>"), {入力名: [InputFile, ...]}, {パラメータ},
     export_figures=False)` で呼ぶ。戻り値の `.files`（出力）/ `.previews`（図）/ `.result`（ログ・警告・data）を確かめる。
     `tests/conftest.py` の `load_input(path)` でファイルを InputFile にできる。
   - 既存ツール（kaiseki-tool）からの移植なら、kaiseki-tool の出力をゴールデンにして一致を確かめる。
   - 新しいツールなら、出力を**手で確かめてから**ゴールデンとして保存する。作り直すときは環境変数
     `SAJI_UPDATE_SNAPSHOTS=1` で書き出す形にする（`tests/test_co2rr_plot.py` が例）。
   - 図の JSON は `tests/golden/figures/<ツール>-<ケース>.json` にスナップショットを置く。
   - 子プロセスで CLI を起動するなど、ネイティブでしか動かないテストには `@pytest.mark.native` を付ける。
8. [ ] **2つの環境でテストを通す**: `uv run pytest -q`（ネイティブ）と Pyodide
   （`uv run python scripts/build_web.py` → `uv run --with playwright python scripts/test_pyodide.py`）。
   Windows で Edge を使うなら環境変数 `SAJI_BROWSER_CHANNEL=msedge`。
9. [ ] **`docs/data-formats.md` に入力形式を書く**（列名・単位・既知の癖）。不明な点は「要確認」。
10. [ ] 図の書き方に手法固有の約束があれば `docs/plotting.md` の「手法ごとの約束」に書く。
11. [ ] **動作を確かめる**: `uv run saji <ツール> --help`、CLI で実際に実行して図（PNG）を目で見る。
    Web は `uv run --with playwright python scripts/check_web.py <ツール> "<入力名>=<ファイル>" --param 名前=値`
    （フォーム・結果・スマートフォン幅のスクリーンショットと zip を保存する）。
12. [ ] README の対応ツールの一覧を更新する。
13. [ ] **版**: 既存ツールの出力が変わるなら `src/saji/__init__.py` の `__version__` を必ず上げ、変更点を
    `docs/decisions/` に記録する。ツールやパラメータを足すだけ（既存の出力が変わらない）なら上げなくてよい
    （manifest.json の git_commit で区別できる）。
14. [ ] `packages` が空でも、`plots=True` なら Web では matplotlib が自動で読み込まれる（`Tool.web_packages`）。

## 出力ファイル名

既存ツールから移植するときは、出力ファイル名・列の順・数値の丸め方を変えない。
変えたほうがよい点に気づいたら、変えずに報告する。
