# 0006 Result に data を持たせ、zip は Python で作る

- 日付: 2026-09-23

## 背景
HANDOFF の Result は「出力ファイル・ログ・警告・図」だった。電気化学の平均電位・溶液抵抗や
CO2RR の集計のように、数値そのものが結果になるツールがある。zip は JS で作る想定だった。

## 決定（人間の承認済み）
- `Result.data`（JSON にできる dict）を持たせる。CLI の `--json` と Web の結果に含める。
- zip は Python の `zipfile` で作る（`core/runner.to_zip`）。JSZip が要らず、CLI と構成を共有できる。
