"""xps-extract: XPS の装置ファイル（.spe）や Multipak の .txt から領域ごとのスペクトルを抜き出す。"""

from __future__ import annotations

from ..core.tool import FileInput, InputError, InputFile, Param, Result, Tool
from ..techniques.xps import extract as ex

TOOL = Tool(
    name="xps-extract",
    summary="XPS の .spe / Multipak .txt から領域ごとのスペクトルを x,y CSV に抜き出す",
    description=(
        "出力は領域ごとに <試料名>_<ラベル>.csv（ヘッダ x,y。x=結合エネルギー/eV）。"
        "試料名はファイル名 <日付>_<氏名>.<測定番号>.<試料名> の末尾。"
        ".spe は実測した全領域が入っているので、labels を指定しなければ全部出す（推奨）。"
        "Multipak の .txt は指定ラベル（既定 Survey）のブロックを抜く。"
        "注意: .spe の軸は装置の生の値、Multipak の書き出しはチャージ補正済みの軸。"
        "そろえるときは energy_shift（C1s 基準のずれ）を指定する。"
        "入力形式は docs/data-formats.md の『PHI .spe』『Multipak Exporter .txt』を参照。"
    ),
    inputs=[
        FileInput("raw", accept=[".spe", ".txt", ".csv"], multiple=True,
                  help="装置の .spe、または Multipak Exporter の .txt / .csv"),
    ],
    params=[
        Param("labels", str, None, group="抽出", label="抽出するラベル",
              help="カンマ区切り（例 Survey,C1s,O1s）。未指定なら .spe は全領域、テキストは Survey。"
                   ".spe では空白と _ の違いを無視して照合する（Cu LMM = Cu_LMM）"),
        Param("energy_shift", float, 0.0, unit="eV", group="抽出", label="エネルギーシフト（チャージ補正）",
              help="結合エネルギー軸に足す値。y は変えない"),
        Param("normalize", bool, True, group="抽出", label="0-1 に正規化",
              help="y を領域ごとに最小0・最大1へ Min-Max 正規化する"),
        Param("offset", int, ex.LABEL_DATA_OFFSET, min=1, unit="行", group="抽出", advanced=True,
              label="データ開始行（テキストのみ）",
              help="Multipak .txt のラベル行からデータ開始行までの行数（書き出し設定により 5 か 2 のことがある）"),
    ],
    examples=[
        "saji xps-extract 20260101_Name.1.sampleA.spe --energy-shift 1.0906",
        "saji xps-extract data/xps/ --labels Survey,C1s --no-normalize",
    ],
)


def run(inputs: dict[str, list[InputFile]], params: dict) -> Result:
    result = Result()
    labels = ex.parse_labels(params["labels"])
    written: dict[str, str] = {}      # 出力名 -> 元ファイル名（衝突の検出用）
    summaries = []
    for f in inputs["raw"]:
        requested = list(labels) if labels is not None else ex.default_labels_for(f.name)
        try:
            spectra = ex.extract_file(f.name, f.data, labels=requested, offset=params["offset"],
                                      normalize=params["normalize"],
                                      energy_shift=params["energy_shift"])
        except ValueError as exc:
            raise InputError(f"{f.name}: {exc}") from exc

        missing = [lb for lb in requested or [] if ex.match_label(lb, spectra) is None]
        for lb in missing:
            result.warn(f"ラベル '{lb}' のデータが見つかりません: {f.name}")
        if not spectra:
            result.warn(f"{f.name}: 抽出できた領域がありません")

        outputs = []
        for label, rows in spectra.items():
            name = ex.output_name(f.name, label)
            if name in written:
                # kaiseki-tool では黙って上書きされていた。後のファイルを残す点は同じ。
                result.warn(f"{name} が重複したので {written[name]} の分を {f.name} の分で上書きしました")
                result.files = [o for o in result.files if o.path != name]
            written[name] = f.name
            result.add_file(name, ex.format_csv(rows))
            result.log(f"[OK] 出力: {name} ({len(rows)}点)")
            outputs.append({"label": label, "file": name, "n_points": len(rows)})
        summaries.append({"file": f.name, "sample": ex.infer_sample_name(f.name),
                          "regions": outputs, "missing_labels": missing})
    result.data["files"] = summaries
    return result
