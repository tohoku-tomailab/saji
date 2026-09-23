# ツールの追加手順

見本は `src/saji/tools/xrd_process.py`（ツール定義）と `src/saji/techniques/xrd.py`（手法の知識）。

## チェックリスト

1. [ ] **CLI 専用にするか決める**（`docs/design.md` の判断基準）。CLI 専用なら `web=False` と
   `cli_only_reason` を書き、理由を `docs/decisions/` に記録する。
2. [ ] **手法の知識を `techniques/<手法>.py` に書く**（読み込み・数値処理・図の組み立て）。
   同じ手法のモジュールが既にあれば足す。入力は bytes / 文字列で受け取る（ファイルパスを受け取らない）。
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
   - 利用者に伝えたいことは `result.log()` / `result.warn()`。機械可読の数値は `result.data`。
   - 利用者が直せる入力の誤りは `InputError` を投げる（CLI の終了コード 2）。
5. [ ] **`registry.py` の `TOOL_MODULES` に1行足す**。
6. [ ] **合成データを `tests/fixtures/<手法>/` に置く**（`tests/fixtures/make_fixtures.py` で作る。
   **実データや、実データを加工したものは置かない**）。
7. [ ] **ゴールデンテストを書く**（`tests/test_<ツール>.py`、期待される出力は `tests/golden/<ツール>/`）。
   既存ツール（kaiseki-tool）からの移植なら、kaiseki-tool の出力をゴールデンにして一致を確かめる。
   図の JSON は `tests/golden/figures/` にスナップショットを置く。
8. [ ] **2つの環境でテストを通す**: `uv run pytest -q`（ネイティブ）と Pyodide（`docs/maintenance.md`）。
9. [ ] **`docs/data-formats.md` に入力形式を書く**（列名・単位・既知の癖）。不明な点は「要確認」。
10. [ ] 図の書き方に手法固有の約束があれば `docs/plotting.md` の「手法ごとの約束」に書く。
11. [ ] `uv run saji <ツール> --help` と、Web（`uv run python scripts/build_web.py` →
    `uv run python -m http.server -d web 8000`）で動作を確かめる。

## 出力ファイル名

既存ツールから移植するときは、出力ファイル名・列の順・数値の丸め方を変えない。
変えたほうがよい点に気づいたら、変えずに報告する。
