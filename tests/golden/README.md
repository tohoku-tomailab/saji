# ゴールデンデータ

期待される出力。`tests/fixtures/` の合成データを入力にして作る。

- `xrd-process/case*-*.xy` … kaiseki-tool（v0.2.0）の `kaiseki xrd process` の出力（改行を LF にそろえたもの）。
  saji の出力がこれと一致することで、移植で数値が変わっていないことを確かめる。
  ヘッダと点数は完全一致、値は最後の桁（1e-6）の違いまで許す（arPLS の計算は CPU によって末尾のビットが変わるため）。
  各ケースのパラメータは `tests/test_xrd_process.py` の `CASES` を参照。
- `co2rr-plot/<ケース>-<名前>_co2rr_summary.csv` … kaiseki-tool の `kaiseki co2rr plot --output data`
  の集計CSV（utf-8-sig。Windows で CRLF になるので改行を LF にそろえたもの）。
  各ケースの引数は `tests/test_co2rr_plot.py` の `CASES` を参照。
- `figures/co2rr-plot-*.json` … co2rr-plot の図の JSON のスナップショット（saji 自身の出力）。
- `echem-extract/<ケース>/` … kaiseki-tool の `kaiseki echem extract` の出力（フェイズごとのCSV・
  `echem_metrics.json`・一括時の `echem_metrics.csv`）。改行を LF にそろえ、指標の `path`（フルパス）を
  落としてある。作り方とケースごとの引数は `echem-extract/from_kaiseki.py`（saji のパラメータとの
  対応は `tests/test_echem_extract.py` の `CASES`）。

ゴールデンデータを作り直すのは、**出力が変わる変更を意図して行い、人間が承認したとき**だけ。

- `xrd-overlay/*.json` … kaiseki-tool（v0.2.0）の `kaiseki.xrd.overlay.overlay()` を上の `xrd-process/*.xy`
  に対して実行し、描いた図（matplotlib の Axes）から拾った期待値（線の y〈オフセット込み・間引き〉、
  オフセット、色、ピーク検出、マーカー位置、物質名の位置と段数、y 範囲）。作り方は
  `xrd-overlay/make_golden.py`（kaiseki-tool の環境で実行する）。ケースの入力とパラメータも JSON に入っている。
- `figures/*.json` … 図の JSON のスナップショット。意図して図を変えたときだけ
  `SAJI_UPDATE_SNAPSHOTS=1 uv run pytest` で作り直す。
- `xps-extract/*.csv` … kaiseki-tool v0.2.0 の `kaiseki xps extract` の出力（csv モジュールの既定どおり CRLF のまま）。
  ケースは `tests/test_xps_extract.py` の `CASES`。
- `xps-plot/*.json` / `xps-fit/*.json` … kaiseki-tool の `prepare_traces` / `prepare_fit_traces` /
  `_prepare_overlay` が出す数値（`tests/fixtures/xps/kaiseki_golden.py` を kaiseki-tool の環境で実行して作る）。
