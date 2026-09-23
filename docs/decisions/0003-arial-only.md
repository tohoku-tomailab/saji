# 0003 図のフォントは Arial に統一し、日本語は警告する

- 日付: 2026-09-23

## 背景
Pyodide には Arial も日本語フォントもない。日本語フォントを同梱すると数MB増える。

## 決定（人間の指示）
- 図の文字はすべて Arial（太字）。軸名・凡例・注釈は英語で書く。
- 日本語フォントは Web に同梱しない。図に Arial で表示できない文字（日本語など）が入ったら、
  runner が警告を出す（`core/plot/checks.py`）。
- matplotlib は Arial が無い環境では Liberation Sans → DejaVu Sans に落ちる（Web 版の成果物画像）。

## 影響
- kaiseki-tool の CO2RR の既定の軸名（「ファラデー効率 / %」「電位 / V」）は英語に変えた。
