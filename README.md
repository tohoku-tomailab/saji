# saji（さじ）

研究室の実験データ処理ツール群です。装置の出力ファイルの読み込み・前処理・集計・グラフ化を、
**ブラウザ**（Web 版）でも **ターミナル**（CLI）でも同じように行えます。

- XRD: 前処理（背景除去・平滑化・規格化・ピーク帰属）、重ね描き
- XPS: 装置ファイル（.spe）/ Multipak からの抽出、重ね描き、フィッティング結果の図示
- CO2RR: ファラデー効率の積み上げ棒グラフ
- 電気化学: ポテンショスタット出力から本測定の抽出、平均電位・溶液抵抗

## データは外部に送信されません

Web 版は、ブラウザの中で Python（[Pyodide](https://pyodide.org/)）を動かして処理します。
選んだファイルはこのコンピュータの外に送信されません。通信するのは、最初に Python 本体と
グラフ描画ライブラリを読み込むときだけです。アクセス解析も入れていません。

## Web 版の使い方

URL: （公開したらここに書く）

1. 左の一覧からツールを選ぶ。
2. 入力ファイルを選ぶ（フォルダごと・ドラッグ＆ドロップも可）。
3. パラメータを調整して「実行」。
4. グラフを確認し、「zip をダウンロード」で結果（処理済みデータ・図・条件の記録）を保存する。
   グラフの凡例と注釈はその場で直せ、PNG / SVG で保存できます。

## CLI の使い方

[uv](https://docs.astral.sh/uv/) が必要です。

```bash
uv tool install git+<リポジトリURL>       # インストール（更新は uv tool upgrade saji）
saji list                                  # ツールの一覧
saji xrd-process --help                    # 使い方
saji xrd-process data/xrd/ --norm max --norm-target 100
```

結果は `outputs/YYYYMMDD_hhmmss-<ツール名>/` に保存され、条件は `manifest.json` に記録されます。
`saji <ツール名> --params outputs/.../manifest.json` で同じ条件をもう一度実行できます。

## AI エージェントと使う

AI エージェント（Claude Code など）に「このデータを処理して」と頼めます。エージェント向けの
説明は [AGENTS.md](AGENTS.md) にあります。Claude Code は **2.1.277 以降** を使ってください
（それ以前の版は AGENTS.md を読みません）。

## 開発

[AGENTS.md](AGENTS.md) と [docs/](docs/) を参照してください。ツールの追加手順は
[docs/adding-a-tool.md](docs/adding-a-tool.md) です。

## サポートとライセンス

研究室内での利用を想定したツールで、サポートは行いません。ライセンスは未定です（決まり次第記載）。
