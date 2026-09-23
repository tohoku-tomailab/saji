# 入力フォーマット辞書

装置やデータの種類ごとの入力形式・列名・単位・既知の癖。研究室固有の知識なので、
コードから読み取れることはすべてここに書く。分からない点は **要確認** と書いて人間に聞く。

## 共通

- 文字コードは自動判定（BOM → CP932 → UTF-8 → Latin-1 の順。`core/tableio.decode_text`）。
  装置の出力は CP932 が多い。BOM 付き UTF-8 は BOM を最優先で信じる（CP932 でも「読めてしまう」ため）。
- 表形式の入力は **列名で列を探す**（列順・列の有無・前置きの行に強い）。列名は全角/半角・大文字小文字・
  記号・空白を無視して照合する（`core/tableio.resolve_columns`）。

## Rigaku SmartLab .TXT（XRD）

- ツール: `xrd-process`
- CP932 のテキスト。先頭に測定条件のヘッダ（`Sample`, `Start`, `Stop`, `Step`, `X-Ray`,
  `ScanningMode`, `Goniometer`, `Attachment` などで始まる行）があり、そのあとに「2θ 強度」の2列が並ぶ。
- ヘッダの行数は一定でないので、**「数値2つだけの行」をデータ行とみなして**抜き出す。
- 2θ の単位は deg、強度は counts。
- 要確認: `*RAS_INT_START` などの区切り行の有無、ステップ・範囲の典型値、1ファイルの大きさ。

## ピーク表 JSON（XRD のピーク帰属）

- ツール: `xrd-process`（入力 `peaks`）
- `[[2θ, 物質名, マーカー, 色], ...]`。例 `[[43.30, "Cu(111)", "v", "tab:red"]]`。
- マーカーは matplotlib の記号（`v` `^` `o` `s` `D` `*` `x` `+`）、色は `tab:red` などの matplotlib の
  色名か `#rrggbb`。マーカーと色は省略可（既定 `v` / `tab:red`）。

## 処理済み XRD .xy

- `xrd-process` の出力。先頭に `# 2theta  intensity  | bg=... smooth=... norm=... bin=...` の
  コメント行、そのあと `%.6f` の2列（2θ、処理後の強度）。
