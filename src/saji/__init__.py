"""saji（さじ）— 研究室の実験データ処理ツール群。

  saji.core        共通の基盤（ツール定義の型・実行・manifest・表の読み込み・図）
  saji.techniques  手法ごとの知識（XRD / XPS / CO2RR / 電気化学）
  saji.tools       1ツール1ファイル（TOOL 定義と run()）
  saji.registry    ツールの一覧（CLI と Web の両方が参照する）
  saji.cli         TOOL 定義から生成する CLI
"""

# 出力が変わる変更をしたら上げる（docs/maintenance.md）。pyproject.toml はここを読む。
__version__ = "0.1.0"
