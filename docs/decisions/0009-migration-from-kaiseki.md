# 0009 kaiseki-tool からの移行で変えた点

- 日付: 2026-09-23
- 状態: **人間の確認待ち**（HANDOFF §10: 既存ツールの出力を変える変更は報告して判断を仰ぐ）

## 変えていないこと（ゴールデンテストで確認）

- 数値の出力（xrd-process の .xy、xps-extract の CSV、co2rr-plot の集計 CSV、echem-extract の
  フェイズ CSV と指標）は kaiseki-tool v0.2.0 とバイト単位で一致する（改行コードを除く。下記）。
- 図の元になる数値（xrd-overlay のオフセット・刻み・ピーク検出と注釈の段積み、xps-plot / xps-fit の
  前処理後の系列）は kaiseki-tool の関数の出力と一致する。
- 出力ファイル名（`<名前>_processed.xy`、`<試料名>_<ラベル>.csv`、`<名前>_co2rr_summary.csv`、
  `<名前>_main.csv` など）と列の順・数値の書式。

## 全体で変えたこと

| 項目 | kaiseki-tool | saji |
|---|---|---|
| 実行 | `kaiseki <手法> <コマンド>`（Typer）、`--config` の多段 JSON | `saji <tool>`、フラットなパラメータ、`--params`（manifest.json も可） |
| 出力先 | 入力の隣・`--out` / `--out-dir` | `outputs/YYYYMMDD_hhmmss-<tool>/` + `manifest.json` |
| 図 | PNG（matplotlib、200 dpi）+ 任意で HTML（plotly） | PNG / SVG / 図の JSON / 図のデータ CSV。Web では Plotly で表示 |
| フォント | Arial + 日本語フォールバック | Arial のみ。日本語は警告（decisions/0003） |
| 既定の軸名 | CO2RR は日本語 | 英語（`Faradaic efficiency / %`、`Potential / V`）。XRD の x は `2θ (deg)`（旧 `2theta (deg)`） |
| 生成物名の下付き | matplotlib の mathtext | `<sub>` |
| CSV の改行 | pandas / csv の既定（Windows では CRLF） | co2rr / echem は LF に固定（OS によらず同じ出力）。xps-extract は csv モジュールの既定の CRLF のまま |
| 図の大きさの指定 | `figsize` / `dpi` / `style_override` / `legend_anchor_x` | 廃止。プリセット `style`（paper / slide / poster）だけ |
| 配色 | 手法ごと | 共通の `SERIES_COLORS`（XPS の3・5・8〜10番目の色が少し変わった） |
| フォルダ入力 | 非再帰の glob（`--pattern`） | 再帰的に、ツールが受け付ける拡張子で拾う |
| 処理できなかったとき | 手法ごとにばらばら（終了コード 0 / 1 / 例外） | 入力の誤りは終了コード 2、処理中のエラーは 1 |
| AgentSkill・設定テンプレート | `.claude/skills/`、`kaiseki config` | 廃止（decisions/0007） |

## ツールごとの主な変更

- **xrd-process**: `--output data/plot/both` を廃止（常に .xy と図の両方）。`--batch` / `--pattern` / `--out-dir` を廃止。
  図の凡例の「processed」の閉じ括弧のずれを直した。
- **xrd-overlay**: `inputs_config` → json パラメータ `traces`。`traces` に無い入力ファイルは描かない
  （kaiseki と同じ。警告を足した）。カラーマップは tab10 / tab20 / viridis だけ。`--out` / `--dpi` / `--html` を廃止。
  描けるデータが無いときは終了コード 2（kaiseki は 0）。
- **xps-extract**: フォルダを渡すと .spe / .txt / .csv をまとめて拾う（kaiseki の既定は `*.txt`）。
  同じ試料名の出力が重なったら警告（kaiseki は黙って上書き）。
- **xps-plot**: 凡例は図全体で1つ（kaiseki はパネルごと）。`group_by=region` で領域ごとのパネル。
  `show_yticks=false` は目盛の数値だけ消す（目盛線は残る）。
- **xps-fit**: `--overlay/--panels` → `overlay`。`residual` と `normalize` に `auto`（モードに応じた kaiseki の既定）。
  `peak_annotate_offsets` の単位を pt から px に（**既存の設定は 4/3 倍する**）。ファイルごとの設定は
  `settings.files[名前]`。残差パネルの x 軸は Plotly で本体とズームが連動しない。
- **co2rr-plot**: 既定の軸名を英語に。電位は凡例に出さない（kaiseki の PNG と同じ）。誤差が全部 0 の系列は
  誤差棒を描かない。`label_pattern` で空欄の行があると kaiseki は pandas 3 で落ちていたが、saji は警告して外す。
- **echem-extract**: 指標から `path`（フルパス）を除いた。指標は常に `echem_metrics.csv` と `echem_metrics.json`
  に出す（kaiseki はフォルダ入力のときだけ CSV）。`cycle` は整数（未指定で全サイクル）。

各ツールの詳しい差分は、移植時の報告（コミットメッセージと `docs/phase0-report.md` 以降の記録）を参照。

## 人間に判断してほしいこと

1. CSV の改行を LF にそろえてよいか（Windows で Excel に読ませるなら CRLF のほうが無難な場合がある）。
2. xrd-overlay の `traces` に無い入力ファイルを、描かない（現状）か、後ろに足して描くか。
3. xps-extract のフォルダ入力で .csv も拾ってよいか。
4. xps-fit の `peak_annotate_offsets` の単位変更（pt → px）。
5. XRD の重ね描きで、最上段の注釈が枠に触れる（kaiseki と同じ余白 0.15×刻み）。余白を広げてよいか。
