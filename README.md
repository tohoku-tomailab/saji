# saji（さじ）

研究室の実験データ処理ツール群です。装置の出力ファイルの読み込み・前処理・集計・グラフ化を、
**ブラウザ**（Web 版）でも **ターミナル**（CLI）でも同じように行えます。

Web 版: **https://tohoku-tomailab.github.io/saji/**

- XRD: 前処理（背景除去・平滑化・規格化・ピーク帰属）、重ね描き
- XPS: 装置ファイル（.spe）/ Multipak からの抽出、重ね描き、フィッティング結果の図示
- CO2RR: ファラデー効率の積み上げ棒グラフ
- 電気化学: ポテンショスタット出力から本測定の抽出、平均電位・溶液抵抗

## データは外部に送信されません

Web 版は、ブラウザの中で Python（[Pyodide](https://pyodide.org/)）を動かして処理します。
選んだファイルはこのコンピュータの外に送信されません。通信するのは、最初に Python 本体と
グラフ描画ライブラリを読み込むときだけです。アクセス解析も入れていません。

## Web 版の使い方

**https://tohoku-tomailab.github.io/saji/**

インストールは不要です。ブラウザ（Chrome / Edge / Firefox / Safari の最近の版）で開くだけで使えます。

1. 左の一覧からツールを選ぶ（スマートフォン幅では上のメニューから選ぶ）。
   ページを開くと裏で Python の読み込みが始まり、右上の表示が「準備完了」になると実行できます
   （初回は数十秒かかることがあります。2回目以降はブラウザのキャッシュで速くなります）。
2. 入力ファイルを選ぶ（フォルダごと・ドラッグ＆ドロップも可）。
3. パラメータを調整して「実行」。あまり使わないものは「詳細設定」に畳んであります。
4. グラフを確認し、「zip をダウンロード」で結果（処理済みデータ・図・条件の記録）を保存する。
   グラフの凡例と注釈はその場で動かしたり書き換えたりでき、「PNG で保存」「SVG で保存」で画像にできます
   （スライドに貼るときはそのままスクリーンショットでも構いません）。

zip の中身は CLI の出力フォルダと同じです。`manifest.json` に使ったパラメータとツールの版が記録されるので、
あとから同じ条件で処理し直せます。

## CLI 版のインストールと使い方

ターミナルから使う版です。大量のファイルをまとめて処理するときや、AI エージェントに処理を頼むときに使います。

### 1. uv を入れる（初回だけ）

[uv](https://docs.astral.sh/uv/)（Python の管理ツール）を入れます。Python 本体（3.14）は uv が自動で用意するので、
別に入れる必要はありません。

```powershell
# Windows（PowerShell）
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

入れたあと、ターミナルを開き直してください。

### 2. saji を入れる

```bash
uv tool install git+https://github.com/tohoku-tomailab/saji
saji list                # ツールの一覧が出れば成功
```

`saji` が見つからないと言われたら `uv tool update-shell` を実行し、ターミナルを開き直してください。

### 3. 更新する

```bash
uv tool upgrade saji
```

GitHub の最新の版（main ブランチ）に更新されます。Web 版は常に最新なので、CLI 版もときどき更新してください。
どの版で処理したかは、出力の `manifest.json` の `tool_version` と `git_commit` で分かります。

うまく更新できないときは、入れ直します。

```bash
uv tool install --reinstall git+https://github.com/tohoku-tomailab/saji
```

### アンインストール

```bash
uv tool uninstall saji
```

### 使い方

```bash
saji list                                   # ツールの一覧
saji xrd-process --help                     # 使い方（入力・パラメータ・単位・既定値・例）
saji xrd-process data/xrd/ --norm max --norm-target 100
saji xrd-process data/xrd/ --dry-run        # 実行せずに、何をするかだけ表示
```

- 入力にはファイル・フォルダ（中のファイルを自動で拾う）・ワイルドカード（`data/*.TXT`）を渡せます。
- 結果は `outputs/YYYYMMDD_hhmmss-<ツール名>/` に保存され、条件は `manifest.json` に記録されます
  （`--output-dir` で保存先の親フォルダを変えられます）。
- `saji <ツール名> <入力> --params outputs/.../manifest.json` で、前回と同じ条件でもう一度実行できます。

## AI エージェントと使う

AI エージェント（Claude Code など）に「このデータを処理して」と頼めます。エージェント向けの
説明は [AGENTS.md](AGENTS.md) にあります。Claude Code は **2.1.277 以降** を使ってください
（それ以前の版は AGENTS.md を読みません）。

## 開発

[AGENTS.md](AGENTS.md) と [docs/](docs/) を参照してください。ツールの追加手順は
[docs/adding-a-tool.md](docs/adding-a-tool.md) です。

## サポートとライセンス

研究室内での利用を想定したツールで、サポートは行いません。ライセンスは未定です（決まり次第記載）。
