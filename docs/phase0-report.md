# フェーズ0 報告：調査と差分（2026-09-23）

HANDOFF.md（改修申し送り書）に基づき、既存の kaiseki-tool を調査して saji の方針を決めた記録。
末尾の「決定事項」が人間の承認を得た内容である。

## 0. 前提

HANDOFF は「既存コードを目標構成へ寄せる」前提で書かれているが、人間の指示により
**saji を新しいリポジトリとして HANDOFF どおりの構成で作り、kaiseki-tool は参考として扱う**。

- kaiseki-tool の処理ロジック（読み込み・数値処理）は移植し、数値結果は既存と一致させる（HANDOFF §10-2）。
- CLI の書き方（Typer）と、手法ごとに書いた matplotlib の描画コードは作り直す。

## 1. 既存ツールの一覧

| 新ツール名 | 旧コマンド | 入力 → 出力 | 依存 | Pyodide | 論点 |
|---|---|---|---|---|---|
| `xrd-process` | `xrd process` | SmartLab `.TXT` → `_processed.xy`・図 | numpy, scipy, pybaselines | ○（pybaselines は純Python。wheel を同梱） | 第2y軸、ピーク注釈の段積み |
| `xrd-overlay` | `xrd overlay` | `.xy` 複数 + ピーク表 → 重ね描き | numpy, scipy | ○ | ファイルごとの色・ラベル・オフセット |
| `co2rr-plot` | `co2rr plot` | 測定CSV → 積み上げ棒・集計CSV | pandas | ○ | 棒と第2y軸 |
| `xps-extract` | `xps extract` | `.spe` / Multipak `.txt` → 領域ごとCSV | 標準ライブラリ | ○ | 図なし |
| `xps-plot` | `xps plot` | 抽出CSV → グループ重ね描き | numpy, pandas | ○ | 複数パネル |
| `xps-fit` | `xps fit` | フィット結果CSV → 成分図 | numpy, pandas | ○ | 塗りつぶし・矢印注釈・残差パネル |
| `echem-extract` | `echem extract` | 装置CSV(cp932) → 本測定CSV + 平均電位・溶液抵抗 | pandas | ○ | 数値指標の返し方 |
| （廃止） | `config list/init` | 設定JSONの雛形 | — | — | TOOL 定義から自動生成に置き換え |

- §3.5 の基準で CLI 専用になるツールは現時点でない（外部バイナリ・並列処理なし、入力は小さい見込み）。
- HANDOFF §1 にある「PDF の操作」は kaiseki-tool に存在しない。
- 実データは kaiseki-tool の git 履歴に含まれていない（`ref/` は一度もコミットされていない）。

## 2. 活かすもの・変えるもの

**活かす**
- `common/tableio`（文字コード自動判定・ヘッダ探索・列名解決）。パス入力を bytes 入力に変える。
- 各手法の解析部分（.spe バイナリ解析、echem のフェイズ解析と指標、XRD 前処理、CO2RR 集計、フィットCSV分解）。
- `common/explore.py` の `base_layout` / `axis_style`（もともと Plotly の dict を組み立てている）。
- スタイルプリセット（paper / slide / poster）。
- CLAUDE.md の「実装して分かった要点」→ `docs/data-formats.md` と `docs/design.md` へ移す。

**変える**
- Typer の手書き CLI → TOOL 定義から argparse で生成。
- 処理中の `print` → Result のログ・警告。
- 手法ごとの matplotlib 描画 → Plotly JSON を組み立て、汎用変換器で matplotlib に描く。
- `plotly` パッケージ依存 → 削除（dict を直接組み立てる）。
- 出力先 → `outputs/YYYYMMDD_hhmmss-{tool}/` + `manifest.json`。フォルダ内のファイル名は既存を保つ。
- Python 3.12 → 3.14（Pyodide 314 に揃える）。
- `.claude/skills/` → 移植しない（AGENTS.md と `--help` で代替）。

## 3. 矛盾・未決だった点と結論

| 論点 | 結論 |
|---|---|
| 図の許可要素（§3.6）に棒・第2y軸・塗りつぶし・複数パネル・矢印注釈がない | **追加する** |
| 構造化した設定（色の辞書、ピーク表、groups など）の渡し方 | ① データ的なもの（ピーク表など）は入力ファイル ② 見た目の辞書は `json` 型パラメータ（例外） ③ `--params run.json` で一括指定（manifest.json をそのまま渡して再実行できる） |
| 成果物の図の形式 | **matplotlib の図（SVG / PNG）と、Origin 等で仕上げやすいCSVの両方**を出す |
| Web 版のフォント | **日本語フォントは同梱しない。すべて Arial に統一し、図に日本語が含まれたら警告する** |
| 図の見た目 | 主な使い方は「Plotly で描いて少しいじり、スクショして進捗スライドに貼る」。**Plotly 側の描画スタイルを主とし、matplotlib 側をそれに揃える** |
| Result に数値データの置き場がない | Result に `data`（JSON化できる dict）を追加し、CLI の `--json` にも含める |
| zip の作成 | Python（`zipfile`）で行う（JSZip 不要、CLI と共通化） |
| パイロット | `xrd-process` |
| リポジトリ | `C:\code\saji` で `git init`。置き場所（研究室 Organization 推奨）とライセンス（MIT 候補）は後で決める |

## 4. 移行計画

- フェーズ1：core（Tool / Param / FileInput / InputFile / Result / manifest）、core/plot（ビルダーと matplotlib 変換器）、生成CLI、最小の Web。パイロットは `xrd-process`。
- フェーズ4：`xps-extract` → `echem-extract` → `xrd-overlay` → `xps-plot` → `co2rr-plot` → `xps-fit`。
- 同じ合成データを kaiseki-tool と saji の両方に通し、数値出力の一致をゴールデンテストで確かめる。
- コマンド名は `saji`。kaiseki の CLI の書き方とは互換を持たせない。出力ファイル名と数値は保つ。

## 5. 確認したバージョン（2026-09-23）

- Pyodide 314.0.7（Python 3.14.2）。numpy 2.4.6 / scipy 1.18.0 / pandas 3.0.2 / matplotlib 3.10.8。pybaselines は同梱されていない。
- Plotly.js 4.1.1（`plotly.js-dist-min`、jsDelivr）。
