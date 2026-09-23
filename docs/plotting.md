# 図の約束

## 方針

- **「何を描くか」は Python（`techniques/`）が決め、「どう描くか」は汎用の描画器が担う。**
- 図は **Plotly の図の形式（`data` と `layout` を持つ dict）** で表す。`plotly` パッケージは使わず、
  `saji.core.plot` のビルダーで組み立てる。
- 描画器は2つあり、どちらも手法の知識を持たない。
  - ブラウザのプレビュー: `web/plot.js`（Plotly.js にそのまま渡す）
  - 成果物の図: `saji.core.plot.mpl`（同じ JSON を matplotlib で SVG / PNG にする）
- **主な使い方は「ブラウザの Plotly で描いて少しいじり、スクショして進捗スライドに貼る」。**
  したがって見た目の基準は Plotly 側。matplotlib 側はそれに揃える（完全一致でなくてよい。
  軸・データ・注釈の内容が一致していればよい）。

## 共通の書式（`core/plot/style.py`）

- フォントは **Arial に統一し、太字**。日本語フォントは同梱しない。図に日本語など Arial に
  無い文字が入ると、runner が警告を出す（`core/plot/checks.py`）。**軸名・凡例・注釈は英語で書く。**
- 背景は白、枠線あり（mirror）、目盛は内向き、グリッドなし。
- 大きさはプリセット `paper` / `slide`（既定）/ `poster`。図を出すツールは `STYLE_PARAM` を
  params に入れ、`get_style(params["style"])` の値（px 単位）を使う。
- 配色は `SERIES_COLORS`（黒→赤→緑→青→水色→紫…）。`layout.colorway` にも入れてあるので、
  色を指定しない系列は Plotly と matplotlib で同じ色になる。
- 凡例は既定で軸の右外（`new_figure(legend="outside")`）。軸内なら `"inside"`。
- 処理条件などの補足はタイトルではなく **副題**（`new_figure(subtitle=...)`）に書く。

## 使ってよい要素（許可リスト）

これ以外の要素が必要になったら、先に人間に相談する（matplotlib 変換器の対応も要る）。

| 要素 | ビルダー | 備考 |
|---|---|---|
| 線・散布図（`scatter`、`mode` = lines / markers） | `add_line` | 線種 solid/dash/dot/dashdot、マーカー circle/square/diamond/triangle-up/-down/cross/x/star |
| 塗りつぶし（`fill` = `tozeroy` / `tonexty`） | `add_line(fill=...)` | XPS のピーク成分など |
| 棒グラフ（`bar`、`barmode` = stack / group、`error_y`、棒中の数値 `text`） | `add_bar` | 積み上げは `layout["barmode"] = "stack"` |
| 軸（タイトル、範囲・片側範囲、逆向き、対数、目盛の表示・非表示） | `set_axis` | |
| 複数パネル（軸の `domain` で縦に並べる） | `set_axis(domain=..., anchor=...)` + `panel_domains` | 各パネルは `xaxisN` / `yaxisN` の組 |
| 第2y軸（`overlaying` + `side="right"`） | `set_axis(overlaying="y", side="right")` | |
| 凡例 | `new_figure(legend=...)` | 系列ごとに `showlegend` |
| 注釈（文字だけ / 矢印つき） | `add_annotation` | `xref`/`yref` はデータ座標か `paper` |
| 縦線・横線・網掛け（`shapes` の line / rect） | `add_vline` / `add_hline` / `add_vrect` | パネルごとなら `yref="y2 domain"` |
| 複数系列のずらし（オフセット） | `offset_values` | 値を足してから `add_line` に渡す |
| タイトルと副題 | `new_figure(title=, subtitle=)` | |

文字の書式は Plotly の簡易 HTML のうち `<sub>` `<sup>` `<br>` だけを使う（例 `H<sub>2</sub>`）。

## 手法ごとの約束

- **XRD**（`techniques/xrd.py`）: x 軸は `2θ (deg)`。規格化したときは左軸=生データと背景（counts）、
  右軸=規格化後（第2y軸、オレンジ）。参照ピークは、ピークが立っている位置にマーカー＋物質名。
  近い注釈は上に段積みする（`layout_peak_annotations`）。
- **XRD 重ね描き**（`xrd.overlay_figure`、xrd-overlay）: 1つの軸にオフセットで積む（ウォーターフォール）。
  既定は入力の先頭が最上段、`bottom_up` で最下段。凡例は常に図の上→下の順。オフセット刻みは
  auto = gap（1.10）× 全系列の最大レンジ、または固定値。系列ごとの基線はその系列色の点線、参照ピークの
  位置に薄い点線。見つかったピークにマーカー、各ピークで最も高い位置に物質名（近い注釈は段積み）。
  y 範囲はデータ + 5% を明示し、上端は注釈に合わせて広げる（Plotly の自動範囲は注釈を含めないため）。
  配色は tab10（11本以上なら viridis）/ tab20 / viridis。
- **CO2RR**（`techniques/co2rr.py`）: 生成物ごとの棒を `barmode="stack"` で積む（下→上 = products /
  stack_order の順、凡例は上の生成物から）。色は固定（H2 灰, CO 黄, CH4 赤, C2H4 紫, CH3COOH 暗赤,
  1-PrOH 濃青, EtOH 緑, HCOOH 水色）。生成物名は `<sub>`。x は分類軸、棒幅 0.6。棒の中に FE の値
  （`min_value_label` 未満は書かない）。誤差は segment（各棒）/ total（高さ0の棒を最上段に積み、二乗和の
  平方根）。電位は第2y軸に線＋四角マーカー（オレンジ #ff7f0e、誤差棒つき、凡例に出さない）。
  既定の軸名は `Faradaic efficiency / %` と `Potential / V`。
- **電気化学**（`techniques/echem.py`）: 成果物の図はない。プレビューだけ、CP は Potential (V) 対 Time (s)
  （フェイズごとに系列）、IMP は Nyquist（Z' 対 -Z''、マーカー付き）で溶液抵抗の位置に破線。
- **XPS**（`techniques/xps/`）: x 軸は `Binding energy / eV` で既定は逆向き、y 軸は `Intensity / a.u.`
  （目盛の数値は出さない）。xps-plot は1グループ = 1パネル（`domain` で縦に並べ、パネル名は paper 座標の注釈）、
  系列は `offset_step` ずつずらす。xps-fit の成分は Spectrum（黒・最前面）/ Composite（赤）/
  Background（灰の破線）/ 各ピーク（青・緑…の順、ピークとバックグラウンドの間を塗る。透明の基準線 +
  `tonexty`、alpha 0.25）/ Residual（濃い灰、0 の点線）。凡例の順は Spectrum → Composite → Background →
  ピーク → Residual。残差の置き場所は offset（データの下）/ panel（上の細いパネル）/ none。
  ピーク注釈は、バックグラウンドを引いた成分の頂点から矢印を出し、その x で一番上の曲線より上に文字を置く。
  overlay は1つの軸に段を積み、試料は凡例ではなく段ラベル（paper x、データ y）で示す。

## 成果物

`Result.add_figure(name, fig)` した図（`export=True`）は、runner が次の4つを出力フォルダに書く。

- `<name>.png` / `<name>.svg` … matplotlib で描いた図（SVG は文字を文字のまま残す）
- `<name>.plotly.json` … 図の JSON（再描画用）
- `<name>_data.csv` … 図の元データ（系列ごとに x / y 列。Origin などで仕上げる用）
