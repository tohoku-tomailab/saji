# 設計判断の記録

1判断1ファイル（日付・背景・決定・却下した案）。新しい判断をしたら番号を振って足す。
「こうしたほうがよいのでは」と思ったら、まずここを読むこと。

| 番号 | 判断 |
|---|---|
| [0001](0001-basic-architecture.md) | 基本構成（Python に統一、コア＋CLI/Web、Pyodide、素の HTML、ツール定義が唯一の情報源） |
| [0002](0002-param-types.md) | パラメータの型に range と json を足す |
| [0003](0003-arial-only.md) | 図のフォントは Arial に統一し、日本語は警告する |
| [0004](0004-plotting.md) | 図は Plotly 形式の JSON。Plotly の見た目を主にし、許可要素を広げる |
| [0005](0005-web-panels.md) | Web の専用パネルの仕組み |
| [0006](0006-result-data-and-zip.md) | Result に data を持たせ、zip は Python で作る |
| [0007](0007-cli-argparse-no-skills.md) | CLI は argparse で生成し、AgentSkill は移植しない |
| [0008](0008-pyodide-tests.md) | Pyodide のテストはブラウザで pytest を動かす自前スクリプト |
| [0009](0009-migration-from-kaiseki.md) | kaiseki-tool からの移行で変えた点 |
