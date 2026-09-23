# 0008 Pyodide のテストはブラウザで pytest を動かす自前スクリプト

- 日付: 2026-09-23

## 背景
HANDOFF は `pytest-pyodide` などで Pyodide 上のテストを行うとしていた。

## 決定
- `scripts/test_pyodide.py`: Web と同じ版の Pyodide をヘッドレスブラウザ（Playwright の chromium）で
  読み込み、ビルド済みの wheel と tests/ を展開して pytest をそのまま実行する。
- テストコードはネイティブと共通。ネイティブでしか意味のないテストだけ `@pytest.mark.native`。

## 却下した案
- pytest-pyodide: テストの書き方が専用（`run_in_pyodide`）になり、Pyodide の配布物一式の取得も要る。
- `pyodide venv`（Node で動かす）: Node と pyodide-build が要る。Web と同じブラウザ環境で確かめたい。
