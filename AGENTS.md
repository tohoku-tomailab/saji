# AGENTS.md — saji（さじ）

研究室の実験データ処理（装置出力の読み込み・前処理・集計・図示）をまとめたツール群。
同じ Python のコアを、**CLI**（人間とエージェント）と **Web**（ブラウザ内の Python = Pyodide）の両方から使う。
対象外: サーバで動くアプリ、実験データの保管、論文用の図の最終仕上げ（CSV を出して他のソフトで仕上げる）。
Web 版: https://tohoku-tomailab.github.io/saji/ / リポジトリ: https://github.com/tohoku-tomailab/saji
（CLI は `uv tool install git+https://github.com/tohoku-tomailab/saji`、更新は `uv tool upgrade saji`）

※ このリポジトリに CLAUDE.md は置かない（置くと AGENTS.md が読まれなくなる）。

## 使い方

```bash
uv sync                                   # 開発環境（Python 3.14）
uv run saji list                          # ツールの一覧
uv run saji <tool> --help                 # 入力・パラメータ（単位・既定値）・例
uv run saji xrd-process data/ --norm max --json      # 実行（要約 JSON を標準出力へ）
uv run saji xrd-process data/ --dry-run   # 書き込まずに計画だけ表示
uv run saji xrd-process data/ --params outputs/<前回>/manifest.json   # 同じ条件で再実行
```

- 出力は `outputs/YYYYMMDD_hhmmss-<tool>/`（`--output-dir` で親を変更）。必ず `manifest.json`
  （版・コミット・パラメータ・入力のファイル名とハッシュ）が入る。
- `--json` の要約: `ok, tool, output_dir, folder, files, n_inputs, warnings, logs, data`（失敗時は
  `ok: false, error, exit_code`）。人間向けの表示は標準エラー。
- 終了コード: 0 成功 / 1 処理中のエラー / 2 引数や入力の誤り。完全に非対話。
- フォルダを渡すと、対応する拡張子のファイルを再帰的に拾う。

## 設計の要点（詳細は [docs/design.md](docs/design.md)）

- **コア＋薄い層**: `src/saji/core/`（型・実行・manifest・図）の上に `cli.py` と `web/` が乗る。
- **ツール定義が唯一の情報源**: `tools/<name>.py` の `TOOL`（入力・パラメータ）から CLI の引数・
  `--help`・Web のフォーム・tools.json を生成する。一覧は `registry.py`。
- **手法の知識は `techniques/`**（読み込み・数値処理・図の組み立て）。ツールはそれを呼ぶだけ。
- **図は Plotly 形式の JSON を Python が組み立てる**（[docs/plotting.md](docs/plotting.md)）。
  ブラウザは Plotly.js、成果物は同じ JSON から matplotlib で SVG/PNG。**Arial のみ・英語表記**。
- **Web は Pyodide**（Web Worker）。サーバなし、データはブラウザの外に出ない。JS は汎用の外枠だけ。
- **CLI 専用（`web=False`）の基準**: 外部バイナリ・subprocess、threading/multiprocessing、
  Pyodide で動かない依存、入力が数百MB超、実行が数十秒を大きく超える、のどれか。

## 却下した案（[docs/decisions/](docs/decisions/)）

Streamlit 等の UI フレームワーク / サーバで動く Web / 処理の JS 再実装 / CLI だけの配布 /
MCP サーバ（今は不要）/ ツールごとの HTML / 手法ごとの JS 描画 / CLAUDE.md。
提案する前に、まず decisions を読むこと。

## 禁止事項

- 実データ（および実データを加工したもの）をコミットしない。テストは合成データだけ（`tests/fixtures/`）。
- `run()` に I/O を入れない（ファイル・print・ネットワーク）。入力は bytes、出力は Result。
- データを外部へ送信するコードを書かない（Web に解析タグも入れない）。
- ツール定義の情報を二か所に書かない（フォームや help を手で書かない）。
- 既存ツールの出力（数値・丸め・列順・ファイル名）を勝手に変えない。変えたいなら報告する。
- 不可逆な git 操作（履歴の書き換え、force push）、公開設定の変更をしない。

## ツールの追加

[docs/adding-a-tool.md](docs/adding-a-tool.md) のチェックリストに従う。要約:
手法の知識を `techniques/` → `tools/<name>.py` に `TOOL` と `run()` → `registry.py` に登録 →
合成データとゴールデンテスト → 2つの環境でテスト → `docs/data-formats.md` を更新。
**JS を書く必要はない**（汎用フォームで足りない操作だけ `web/panels/<tool>.js`。理由を decisions に記録）。

## テスト

```bash
uv run pytest -q                                            # ネイティブ
uv run python scripts/build_web.py                          # Web のビルド（web/dist）
uv run --with playwright python scripts/test_pyodide.py     # Pyodide（初回は playwright install chromium）
uv run --with playwright python scripts/check_web.py <tool> "<入力名>=<ファイル>"   # Web で1ツールを実行して確認
uv run python -m http.server -d web 8000                    # Web を手元で確認 → http://localhost:8000/
# Windows で Edge を使うなら、Playwright を使う2つの前に SAJI_BROWSER_CHANNEL=msedge を設定する
git config core.hooksPath scripts/hooks                     # pre-commit フック（実データ・生成物の混入防止）
```

## 判断に迷ったとき（優先順位）

1. 実験データを守る（外部に送信しない、リポジトリに入れない）
2. 処理結果の正しさと再現性（既存と結果が変わるなら必ず報告）
3. 後任が保守できること（Python だけで完結、単純、ドキュメントがある）
4. 研究室メンバーにとっての使いやすさ
5. 性能と見た目

それでも決められないときは、実装せずに人間へ質問する。

## ドキュメント

[design.md](docs/design.md) 設計 / [plotting.md](docs/plotting.md) 図 /
[data-formats.md](docs/data-formats.md) 装置の入力形式 / [adding-a-tool.md](docs/adding-a-tool.md) /
[maintenance.md](docs/maintenance.md) 年次更新・デプロイ / [decisions/](docs/decisions/) 設計判断 /
[HANDOFF.md](docs/HANDOFF.md) 最初の申し送り書
