# 公開準備のチェック（HANDOFF §8、2026-09-23 時点）

**公開設定の変更は人間が行う。** ここでは調べた結果だけを記録する（削除や履歴の書き換えはしていない）。

2026-09-23 に https://github.com/tohoku-tomailab/saji （Public）へ公開し、Web 版を
https://tohoku-tomailab.github.io/saji/ で公開した（人間の判断）。以下は公開前に調べた結果。

## 実データの混入

- 現在のファイル・git の履歴全体とも、実データは見つからなかった。`tests/fixtures/` はすべて生成スクリプト
  （`tests/fixtures/<手法>/make.py`）で作った合成データ。
- 200 KB を超えるファイルは履歴に無い。

## 機微な情報の候補（人間が判断する）

| 候補 | 場所 | 内容 |
|---|---|---|
| コミットの作者名とメールアドレス | git の履歴全体（全コミット） | 個人の GitHub 名と個人のメールアドレス。公開すると誰でも見える。研究室の Organization に置くなら、noreply アドレスへの変更を検討（履歴の書き換えが要るので人間が判断） |
| 試料名の付け方 `CupH7fA` / `reCupH7fA` など | `src/saji/techniques/co2rr.py`・`tools/co2rr_plot.py`（説明・例）、`tests/fixtures/co2rr/`、`tests/test_co2rr_plot.py`、`tests/test_xps_extract.py` | kaiseki-tool の例から引き継いだ試料名の形。値は合成だが、名前の付け方は実際の試料に由来する可能性がある |
| 試料名 `rc8` / `rc9` とチャージ補正の値 +1.0906 / +0.4838 eV | `tests/test_xps_extract.py`、`docs/data-formats.md` | 実データでの確認結果（kaiseki-tool の記録）に由来 |
| 研究の題材（Cu 触媒・CO2 還元・合成時 pH、TiO2） | XRD のピーク表の例、CO2RR の例と fixtures | 研究テーマが推測できる。未発表の内容に当たるかは要確認 |
| 装置名（Rigaku SmartLab、PHI VersaProbe / PHI5000、北斗電工 HZ 系） | docs・コメント | 研究室の保有装置が分かる。通常は問題ない |

ローカルの絶対パス・個人名（コミット作者を除く）・共同研究先・装置のシリアル番号は見つからなかった。

## 準備済み

- pre-commit フック（`scripts/hooks/pre-commit`。`git config core.hooksPath scripts/hooks` で有効化）:
  `outputs/` `data/` `ref/` `web/dist/` の中身、1 MB を超えるファイル、装置データらしい拡張子
  （`tests/fixtures/` などを除く）のコミットを拒否する。
- `.gitignore`: outputs/、web/dist/、data/、ref/、仮想環境、キャッシュ。

## 未決（人間が決める）

- LICENSE の種類（候補 MIT）。まだ置いていない。
- Public にするかどうかと時期（指導教員の了承、知財ポリシー、共同研究契約の確認）。
- リポジトリの置き場所（研究室の GitHub Organization を推奨）。
