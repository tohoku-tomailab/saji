# 0005 Web の専用パネルの仕組み

- 日付: 2026-09-23

## 背景
原則としてツールを足すときに JS を書かない。ただし、グラフ上をドラッグして範囲を決めるなど、
汎用フォームで表せない操作が要るツールがありうる。

## 決定
- `web/panels/<tool>.js` があれば、ビルド時に tools.json の `panel: true` になり、外枠はパラメータ欄の
  代わりにそれを読み込む。
- 形式は ES module: `export function mount(container, ctx) -> { getParams() }`。
  `ctx = { tool, defaults, getFiles(inputName) }`。処理そのものは Python の run() が行う。
- 専用パネルを作るときは、その理由をこのフォルダに記録する。
- 2026-09-23 時点で専用パネルはない。候補: XPS のチャージ補正（C1s ピークをクリックしてシフト量を決める）、
  XPS フィットの注釈位置の調整。
