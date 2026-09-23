# ゴールデンデータ

期待される出力。`tests/fixtures/` の合成データを入力にして作る。

- `xrd-process/case*-*.xy` … kaiseki-tool（v0.2.0）の `kaiseki xrd process` の出力（改行を LF にそろえたもの）。
  saji の出力がこれと一致することで、移植で数値が変わっていないことを確かめる。
  各ケースのパラメータは `tests/test_xrd_process.py` の `CASES` を参照。

ゴールデンデータを作り直すのは、**出力が変わる変更を意図して行い、人間が承認したとき**だけ。
