# 設計

HANDOFF.md（最初の申し送り書）の §2〜§6 を、恒久的な設計文書として書き直したもの。
判断の経緯は `docs/decisions/` を参照。

## 目的

1. 研究室メンバーがブラウザで開くだけで使える（Web）。
2. AI エージェントが CLI から呼び出せる。
3. 作成者がいなくなっても、後任が AI エージェントと対話するだけで保守・機能追加できる。

## 構成

```
src/saji/
  core/          共通の基盤（手法の知識は持たない）
    tool.py      Tool / Param / FileInput / InputFile / Result / InputError
    runner.py    実行（パラメータ検証 → run() → 図の書き出し → manifest）と zip
    tableio.py   文字コード自動判定・ヘッダ探索・列名解決（崩れたCSVに強い）
    version.py   版・git コミット・Pyodide の版
    plot/        図の JSON のビルダー・スタイル・matplotlib 変換器・図のデータCSV・Arial 検査
  techniques/    手法ごとの知識（XRD / XPS / CO2RR / 電気化学）。図の組み立てもここ
  tools/         1ツール1ファイル（TOOL と run()）
  registry.py    ツールの一覧（CLI と Web の両方が参照する）
  cli.py         TOOL 定義から argparse の CLI を生成
  web.py         Pyodide から呼ぶ入口（web/worker.js だけが使う）
web/             汎用の外枠（index.html / app.js / worker.js / plot.js / style.css / panels/）
scripts/         build_web.py（Web のビルド）/ test_pyodide.py / hooks/pre-commit
tests/           fixtures（合成データ）/ golden（期待される出力）
```

## ツール定義（唯一の情報源）

各ツールは `TOOL = Tool(...)` と `run(inputs, params) -> Result` の組。CLI の引数・`--help`・
Web のフォーム・tools.json はすべて TOOL から生成する。

- `inputs`: `FileInput(name, accept=[拡張子], multiple, required, help)`。1つ目が CLI の位置引数。
- `params`: `Param(name, type, default, help, label, unit, choices, min, max, group, advanced)`。
  型は int / float / str / bool / choice / range / json（json は例外。decisions/0002）。
  `default=None` は「未指定なら使わない」。
- `packages`: Pyodide で読み込むパッケージ。`plots=True` なら Web で matplotlib も読み込む。
- `web=False` と `cli_only_reason`: CLI 専用のツール。

## run() の約束

- ファイルシステムに触れない（入力は bytes、出力も bytes）。パスの解決・書き込みは CLI / Web の層。
- 画面を知らない（print しない）。`result.log()` / `result.warn()` / `result.data`（機械可読の数値）。
- 決定的にする（乱数は seed をパラメータに）。ネットワークに接続しない。
- 利用者が直せる入力の誤りは `InputError`（CLI の終了コード 2）。
- 依存を足すときは Pyodide で動くことを確かめ、理由を docs に残す（`web=False` 専用の依存は除く）。

## Result と runner

`Result` は `files`（相対パスと bytes）/ `logs` / `warnings` / `figures` / `data` を持つ。
runner（`core/runner.py`）が次を行う。

1. パラメータを型変換し、未指定を既定値で埋める（未知のパラメータは InputError）。
2. 入力を検証（必須・個数・拡張子の警告）。
3. `run()` を呼ぶ。
4. 図ごとに Arial で表示できない文字を検査して警告し、`export=True` の図を
   `<名前>.png / .svg / .plotly.json / _data.csv` に書き出す。
5. `manifest.json` を作る。

## 出力規約

- CLI の出力先は `outputs/YYYYMMDD_hhmmss-{tool}/`（ローカル時刻）。同じ秒なら `-2`, `-3` …。
- Web は同じ構成の zip（`YYYYMMDD_hhmmss-{tool}.zip`、中にフォルダ）。zip は Python の zipfile で作る。
- `manifest.json`: tool / tool_version / git_commit / runtime（cli / web）/ python_version /
  pyodide_version / started_at / finished_at（時差つき）/ params / inputs（入力名・ファイル名・
  サイズ・sha256。**フルパスは記録しない**）/ outputs / warnings。
- `--params manifest.json` で同じ条件を再現できる。

## CLI

- `saji <tool> [入力...] [--param 値 ...] [--params JSON] [--output-dir] [--json] [--dry-run]`、`saji list`。
- 完全に非対話。人間向けのメッセージは標準エラー、`--json` の要約だけ標準出力。
- 終了コード 0 / 1（処理中のエラー）/ 2（引数や入力の誤り）。
- 入力はファイル・フォルダ（再帰、拡張子で絞る）・ワイルドカード（Windows でも展開する）。
- 配布は `uv tool install git+<リポジトリURL>`。

## Web（Pyodide）

- 外枠は1つ（`web/index.html`）。tools.json からツール一覧とフォームを即座に表示し、並行して
  Worker が Pyodide と saji の wheel を読み込む。ツールを選ぶとその `packages` を読み込む。
- Pyodide は module worker で動かす（314 系は classic worker 不可）。UI スレッドで Python を実行しない。
- Pyodide と Plotly.js の版は固定（`scripts/build_web.py` の `PYODIDE_VERSION`、`index.html`）。
- フォルダ入力（webkitdirectory）とドラッグ＆ドロップに対応。出力は zip。
- 外部へ送信しない。解析タグも入れない。画面に明記する。通信は Pyodide と Plotly.js の読み込みだけ。
- 汎用フォームで足りないツールだけ `web/panels/<tool>.js`（decisions/0005）。

### CLI 専用（`web=False`）にする基準

どれか1つに当てはまれば CLI 専用。Web の一覧には「CLI専用」と表示し、CLI の使い方を案内する。

- 外部バイナリ（Ghostscript、OCR など）や subprocess が必要
- threading / multiprocessing が必要
- Pyodide で動かない依存がある
- 1回の入力が数百MBを超える（ブラウザのメモリは実用上 2GB 程度。pandas は元の数倍に膨らむ）
- Pyodide 上の実行時間が数十秒を大きく超える

## 図

`docs/plotting.md` を参照。要点: Plotly 形式の JSON を Python が組み立て、ブラウザは Plotly.js、
成果物は matplotlib。Plotly の見た目が主（スクショしてスライドに貼る）。Arial のみ。

## 再現性とバージョン

- 版は `src/saji/__init__.py` の `__version__`（pyproject が読む）。**出力が変わる変更をしたら上げる。**
- CLI の Python と Pyodide の Python を揃える（Pyodide 314.x = Python 3.14）。numpy / scipy /
  pandas / matplotlib も Pyodide に同梱の版に合わせる（pyproject.toml）。

## テスト

- `tests/fixtures/` は合成データだけ。生成スクリプト `tests/fixtures/<手法>/make.py`。
- ツールごとにゴールデンテスト（`tests/golden/`）。kaiseki-tool から移植したツールは、
  kaiseki-tool の出力をゴールデンにしている。
- 図の JSON はスナップショット（`tests/golden/figures/`）。matplotlib 変換は許可要素ごとに描けることをテスト。
- ネイティブ（pytest）と Pyodide（`scripts/test_pyodide.py`）の両方で通す。CI は `.github/workflows/ci.yml`。
