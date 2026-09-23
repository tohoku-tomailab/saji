# 0004 図は Plotly 形式の JSON。Plotly の見た目を主にし、許可要素を広げる

- 日付: 2026-09-23

## 背景
HANDOFF は「何を描くかは Python、図は Plotly の JSON、ブラウザは Plotly.js、成果物は同じ JSON から
matplotlib」と決めていた。許可要素は線・散布図・軸・凡例・注釈・縦線と網掛け・オフセットだった。
実際の使い方は「Plotly で描いて少しいじり、スクショして進捗共有スライドに貼る」が大部分。

## 決定（人間の承認済み）
- 見た目の基準は Plotly 側。スライドにそのまま貼れる大きさ・太さ（プリセット paper/slide/poster）。
  matplotlib 変換器はそれに揃える（完全一致でなくてよい）。
- ブラウザでは凡例・軸名・注釈を図の上で編集・移動でき、PNG / SVG で保存できる。
- 許可要素に、棒グラフ（積み上げ・誤差棒・数値ラベル）、第2y軸、塗りつぶし（tozeroy / tonexty）、
  複数パネル（domain）、矢印つき注釈を足す（kaiseki-tool の CO2RR / XPS の図に必要）。一覧は docs/plotting.md。
- 成果物は PNG / SVG / 図の JSON / 図のデータ CSV（Origin などで仕上げる用）の4つ。
