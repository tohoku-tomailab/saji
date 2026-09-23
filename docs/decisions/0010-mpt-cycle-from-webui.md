# 0010 mpt-cycle-extractor-webui を mpt-cycle として移植

- 日付: 2026-09-23
- 状態: 決定（人間に確認済み）

## 背景

[mpt-cycle-extractor-webui](https://github.com/tohoku-tomailab/mpt-cycle-extractor-webui)（commit d4b755f）は、
EC-Lab の .mpt から指定サイクルを抜き出して RHE 換算した CSV を出し、CV を重ね描きする単一 HTML のツール。
処理を JS で書いているので、saji の方針（処理は Python、JS は汎用の外枠だけ）に合わせて Python に移した。

## 決定

- ツール名は `mpt-cycle`、手法の知識は `techniques/eclab.py`（北斗電工の CSV を扱う `echem.py` とは形式が別なので分けた）。
- **CSV は移植元とバイト単位で同じ**（ファイル名・列・値の文字列・E_RHE の書式・全欄のダブルクォート・CRLF・BOM）。
  移植元の JS を Node で動かした出力をゴールデンにして確かめる（`tests/golden/mpt-cycle/from_webui.mjs`）。
- 文字コードの判定（UTF-8 → Shift_JIS）と列名の照合も移植元のまま（`core/tableio` の判定は使わない。
  CP932 を先に試すので、UTF-8 のファイルで結果が変わりうるため）。
- 図の体裁は saji の方式に置き換えた（人間に確認済み）。

## 移植元から変えたこと

| 項目 | 移植元 | saji |
|---|---|---|
| 入力の拡張子 | .mpt と .txt | .mpt だけ（フォルダを再帰的に拾うとき、関係ない .txt を拾わないため。人間に確認済み） |
| 読めないファイル | 一覧に赤字で表示 | 警告して飛ばす。1つも処理できなければ終了コード 2 |
| pH・温度・参照電極の誤り | ファイルごとのエラー | 実行前に InputError。pH の範囲 0–14.5 はパラメータの範囲として検査（RHE オフでも） |
| 参照電極 | 選択肢 + 数値欄（数値を変えると Custom） | `reference`（プリセット）+ `ref_potential`（指定すればプリセットより優先。custom では必須） |
| Hg/HgO (1 M KOH) | コード 0.105 V（README は古い 0.098 V のまま） | 0.105 V（人間に確認済み） |
| 図の列の既定 | 全ファイルの列の和から候補の順に1つ選ぶ（`<I>/mA` と `I/mA` のファイルを混ぜると一方が描かれない） | **ファイルごとに**候補の順で選ぶ。軸名がファイルによって違えば警告 |
| 軸名の既定 | 固定 `E / V vs. RHE`、`I / mA`（RHE オフや I/A でも同じ） | 列名から作る（`E_RHE/V` → `E / V vs. RHE`、`Ewe/V` → `E / V`、`<I>/mA` → `I / mA`） |
| 図の体裁 | 幅・高さ・線の太さ・PNG 倍率・グリッド・凡例の四隅・体裁 JSON・localStorage | プリセット `style`、凡例 inside/outside/none、範囲・タイトル・軸名。条件の再利用は `--params` / manifest.json |
| 系列の表示・色・凡例名 | 画面のチェック・色・名前の欄 | `traces`（JSON。xrd-overlay と同じ形）。Web では凡例のクリックでも隠せる |
| 配色 | 独自の8色 | 共通の `SERIES_COLORS` |
| 図の名前 | 1本ならその CSV の名前、複数なら `CV_cycle<N>[_RHE]_overlay` | 同じ |

## 人間に確認して決めたこと（2026-09-23）

1. 文字コードは移植元と同じ UTF-8 → Shift_JIS の順のままにする（移植元で動作を確かめてあるため）。
   CP1252 で書かれた `µ` や `°` は半角カナに化けうるが、実データで問題が出たら改めて検討する。
2. 移植元のリポジトリと公開ページは、当面そのまま残す。
