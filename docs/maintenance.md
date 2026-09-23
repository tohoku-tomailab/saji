# 定期メンテナンス

## 年1回: Pyodide と Python の更新

Pyodide のメジャー版は Python の更新に合わせて年1回出る（例 314.x = Python 3.14）。

1. Pyodide の changelog で新しい版と、その Python の版、同梱パッケージの版を確かめる。
   同梱パッケージの版は `https://cdn.jsdelivr.net/pyodide/v<版>/full/pyodide-lock.json` で分かる。
2. `scripts/build_web.py` の `PYODIDE_VERSION` を上げる。
3. `pyproject.toml` の `requires-python` と `.python-version`、依存（numpy / scipy / pandas /
   matplotlib）の版の範囲を、Pyodide の同梱版に合わせる。`uv sync`。
4. Worker の読み込み方（`web/worker.js`）が変わっていないか changelog で確かめる
   （例: 314 で classic worker が使えなくなった）。
5. `uv run pytest -q`、`uv run python scripts/build_web.py`、
   `uv run --with playwright python scripts/test_pyodide.py`、ブラウザで手動確認。
6. ゴールデンテストが落ちたら、**数値が変わった理由を調べて人間に報告する**（依存の更新で
   結果が変わることがある）。承認されたらゴールデンを作り直し、`__version__` を上げる。

## 依存の更新

- Plotly.js は `web/index.html` の `<script src=...@版>` で固定している。上げたら図の見た目を確認する。
- 同梱する純 Python の依存（`scripts/build_web.py` の `VENDORED`、今は pybaselines）は、
  ビルド時に手元の環境と同じ版の wheel を PyPI から取ってくる。版は `uv.lock` で決まる。
- 依存を足すときは Pyodide で動くか確かめ（同梱されているか、純 Python の wheel があるか）、
  足した理由を docs に残す。

## Web 版のデプロイ（GitHub Pages）

1. リポジトリの Settings → Pages で Source を「GitHub Actions」にする（公開は人間が判断する）。
2. Actions タブで `deploy-pages` を手動実行する（テスト → `build_web.py` → `web/` を公開）。
3. 公開された URL を README に書く。

手元で確認するときは `uv run python scripts/build_web.py` のあと
`uv run python -m http.server -d web 8000` で http://localhost:8000/ を開く
（Worker は file:// では動かないので、必ずローカルサーバ経由で開く）。

## ゴールデンデータ

`tests/golden/` は「期待される出力」。作り直すのは、出力が変わる変更を意図して行い、
人間が承認したときだけ。作り直したら `__version__` を上げる。
