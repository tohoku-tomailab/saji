"""XPS（X線光電子分光）の手法知識。

  spe      … PHI の装置ファイル .spe（バイナリ）の解析
  extract  … .spe / Multipak Exporter の .txt からの領域の抽出（xps-extract）
  plot     … 抽出済み x,y CSV の重ね描き（xps-plot）
  fit      … ピークフィッティング結果 CSV の図示（xps-fit）

数値処理は kaiseki-tool の xps/ と等価に保つ。入力形式は docs/data-formats.md の
「XPS」の各節を参照。結合エネルギー軸は既定で反転（大→小）する。
"""

DEFAULT_XLABEL = "Binding energy / eV"
DEFAULT_YLABEL = "Intensity / a.u."
DEFAULT_OFFSET_STEP = 1.2
