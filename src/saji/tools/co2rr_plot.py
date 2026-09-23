"""co2rr-plot: CO2RR の測定CSVから、ファラデー効率の積み上げ棒グラフ（+ 電位）を作る。"""

from __future__ import annotations

import re

from ..core.plot import STYLE_PARAM, get_style
from ..core.tool import FileInput, InputError, InputFile, Param, Result, Tool
from ..techniques import co2rr

TOOL = Tool(
    name="co2rr-plot",
    summary="CO2RR の測定CSVから、ファラデー効率の積み上げ棒グラフ（右軸に電位）を作る",
    description=(
        "同じラベルの行（試料）をまとめて平均し、誤差（std / sem）をエラーバーで付ける。"
        "ラベルは labels（sample_id → ラベル）> label_pattern（正規表現で抽出）> ラベル元の列"
        "（label_col > group > label > sample_name > sample_id）の順で決まる。"
        "出力は集計表 <名前>_co2rr_summary.csv（ラベルごとの n・平均・誤差）と図 <名前>_co2rr。"
        "入力形式は docs/data-formats.md の『CO2RR 測定CSV』を参照。"
    ),
    inputs=[
        FileInput("csv", accept=[".csv"],
                  help="CO2RR の測定CSV（sample_id, sample_name, 生成物の FE%, potential。列順・別名は自由）"),
    ],
    params=[
        # ---- 集計 ----
        Param("products", str, ",".join(co2rr.DEFAULT_PRODUCTS), group="集計", label="生成物",
              help="生成物の列（カンマ区切り。並び順が積み上げの下→上）。CSV に無い列は無視する"),
        Param("label_col", str, None, group="集計", label="ラベル元の列",
              help="ラベル元の列（sample_id / sample_name / group / label など。"
                   "未指定なら group > label > sample_name > sample_id の順）"),
        Param("label_pattern", str, None, group="集計", label="ラベル抽出の正規表現",
              help="ラベル元の文字列から正規表現で抜き出す（例 pH\\d+ で synthCupH7fA → pH7。"
                   "グループ () があれば1つ目）"),
        Param("labels", "json", None, group="集計", label="ラベルの個別指定", advanced=True,
              help='sample_id → ラベルの辞書（最優先。例 {"S03_CupH7r": "pH7"}）'),
        Param("error", choices=co2rr.ERRORS, default="std", group="集計", label="誤差",
              help="誤差の種類（std=標準偏差 / sem=標準誤差 / none=なし）"),
        Param("label_order", str, None, group="集計", label="横軸の並び順",
              help='ラベルの並び順（カンマ区切り、または JSON のリスト ["pH7", "pH9"]）。'
                   "書かなかったラベルは図と集計表から外れる。未指定なら CSV に出てきた順"),
        # ---- 図 ----
        Param("ylim", "range", None, unit="%", group="図", label="左軸の範囲",
              help="ファラデー効率の軸の範囲（例 0,120）"),
        Param("ylim2", "range", None, unit="V", group="図", label="右軸の範囲",
              help="電位の軸の範囲（例 -1.9,-1.4）"),
        Param("xlabel", str, None, group="図", label="横軸の名前", help="横軸の名前"),
        Param("ylabel", str, co2rr.YLABEL, group="図", label="左軸の名前", help="左軸の名前"),
        Param("potential_label", str, co2rr.POTENTIAL_LABEL, group="図", label="右軸の名前",
              help="右軸（電位）の名前"),
        Param("title", str, None, group="図", label="タイトル", help="図のタイトル"),
        Param("show_potential", bool, True, group="図", label="電位を描く",
              help="電位の列があるとき、右軸に電位を描く"),
        Param("show_values", bool, True, group="図", label="数値を書く",
              help="棒の各区分の中にファラデー効率の数値を書く"),
        Param("min_value_label", float, 3.0, min=0, unit="%", group="図", advanced=True,
              label="数値を書く下限", help="この値未満の区分には数値を書かない"),
        Param("error_mode", choices=co2rr.ERROR_MODES, default="segment", group="図",
              label="エラーバーの位置",
              help="segment=各生成物の上端 / total=積み上げの上端に合計の誤差（二乗和の平方根）/ none=描かない"),
        Param("colors", "json", None, group="図", advanced=True, label="生成物の色",
              help='生成物 → 色の辞書（既定の色を上書き。例 {"H2": "#808080"}）'),
        Param("stack_order", str, None, group="図", advanced=True, label="積み上げ順",
              help="積み上げの順（下→上。カンマ区切り）。書かなかった生成物は図に出ない。"
                   "未指定なら products の順"),
        STYLE_PARAM,
        # ---- 列名（詳細） ----
        Param("id_col", str, "sample_id", group="列名", advanced=True, label="試料IDの列",
              help="試料IDの列の論理名（別名 id / sample / 試料ID も探す）"),
        Param("name_col", str, "sample_name", group="列名", advanced=True, label="試料名の列",
              help="試料名の列の論理名（別名 name / 試料名 も探す）"),
        Param("potential_col", str, "potential", group="列名", advanced=True, label="電位の列",
              help="電位の列の論理名（別名 電位 / voltage / overpotential / 過電圧 なども探す）。"
                   "集計表の列名にもなる"),
    ],
    packages=["numpy", "pandas"],
    plots=True,
    examples=[
        'saji co2rr-plot data.csv --label-pattern "pH\\d+"',
        'saji co2rr-plot data.csv --label-pattern "pH\\d+" --ylim 0,120 --ylim2 -1.9,-1.4 --error sem',
        'saji co2rr-plot data.csv --label-order "pH7,pH9,pH11" --error-mode total',
    ],
)


def _names(params: dict, key: str) -> list[str] | None:
    try:
        return co2rr.parse_name_list(params[key])
    except ValueError as exc:
        raise InputError(f"{key} を読めません: {exc}") from exc


def _dict_param(params: dict, key: str) -> dict[str, str] | None:
    value = params[key]
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InputError(f"{key} は JSON の辞書（{{\"名前\": \"値\"}}）にしてください")
    return {str(k): str(v) for k, v in value.items()}


def run(inputs: dict[str, list[InputFile]], params: dict) -> Result:
    result = Result()
    f = inputs["csv"][0]
    products = _names(params, "products") or list(co2rr.DEFAULT_PRODUCTS)
    label_order = _names(params, "label_order")
    stack_order = _names(params, "stack_order")
    label_map = _dict_param(params, "labels")
    colors = _dict_param(params, "colors")
    id_col, name_col, pot_col = params["id_col"], params["name_col"], params["potential_col"]
    if params["label_pattern"]:
        try:
            re.compile(params["label_pattern"])
        except re.error as exc:
            raise InputError(f"label_pattern が正規表現として不正です: {exc}") from exc

    # ---- 読み込み ----
    try:
        df, present, hinted = co2rr.load_co2rr(f.text(), products=products, id_col=id_col,
                                               name_col=name_col, potential_col=pot_col)
    except ValueError as exc:
        raise InputError(f"{f.name}: {exc}") from exc
    if not hinted:
        result.log(f"[{f.name}] 列 {products[:2]} を含む行が見つからないので、先頭行をヘッダとみなしました")
    missing = [p for p in products if p not in present]
    if missing:
        result.log(f"CSV に無い生成物（無視）: {', '.join(missing)}")
    if pot_col not in df.columns:
        result.log(f"電位の列（{pot_col}）がありません")

    # ---- ラベル付け ----
    if params["label_col"] and params["label_col"] not in df.columns:
        result.warn(f"label_col={params['label_col']!r} は読み込んだ列（{', '.join(map(str, df.columns))}）"
                    "に無いので無視しました")
    try:
        source = co2rr.label_source(df, id_col=id_col, name_col=name_col, label_col=params["label_col"])
        df = co2rr.assign_labels(df, id_col=id_col, name_col=name_col, label_col=params["label_col"],
                                 label_map=label_map, label_pattern=params["label_pattern"])
    except ValueError as exc:
        raise InputError(f"{f.name}: {exc}") from exc
    result.log(f"ラベル元の列: {source}" + (f"（正規表現 {params['label_pattern']}）"
                                          if params["label_pattern"] else ""))
    if label_map and id_col in df.columns:
        ids = set(df[id_col].astype(str))
        unknown = [k for k in label_map if k not in ids]
        if unknown:
            result.warn(f"labels の sample_id が CSV にありません: {', '.join(unknown)}")
    blank = int(df["label"].isna().sum())
    if blank:
        result.warn(f"ラベル元（{source}）が空欄の {blank} 行は集計から外しました")

    # ---- 集計 ----
    agg = co2rr.aggregate(df, present, potential_col=pot_col, error=params["error"],
                          label_order=label_order)
    if agg.empty:
        raise InputError("集計できる群がありません（label_order とラベルが一致しているか確認してください）")
    if label_order:
        labels_in = list(dict.fromkeys(df["label"].dropna()))
        absent = [lab for lab in label_order if lab not in labels_in]
        if absent:
            result.warn(f"label_order のうちデータに無いラベル（無視）: {', '.join(absent)}")
        dropped = [lab for lab in labels_in if lab not in label_order]
        if dropped:
            result.warn(f"label_order に無いので図と集計表から外したラベル: {', '.join(dropped)}")
    if stack_order:
        unknown = [p for p in stack_order if p not in present]
        if unknown:
            result.warn(f"stack_order のうち CSV に無い生成物（無視）: {', '.join(unknown)}")

    result.log(f"[{f.name}] {len(df)}行 -> {len(agg)}群 / 生成物 {present} / 誤差={params['error']}")
    for lab, n in zip(agg["label"], agg["n"]):
        result.log(f"  {lab}: n={n}")

    result.add_file(f"{f.stem}_co2rr_summary.csv", co2rr.format_summary_csv(agg), encoding="utf-8-sig")
    result.data["products"] = present
    result.data["n_rows"] = int(len(df))
    result.data["groups"] = co2rr.summary_records(agg)

    # ---- 図 ----
    st = get_style(params["style"])
    try:
        fig = co2rr.co2rr_figure(
            agg, present, st, potential_col=pot_col, colors=colors, stack_order=stack_order,
            ylim=params["ylim"], ylim2=params["ylim2"], xlabel=params["xlabel"],
            ylabel=params["ylabel"], potential_label=params["potential_label"],
            title=params["title"], show_potential=params["show_potential"],
            show_values=params["show_values"], min_value_label=params["min_value_label"],
            error_mode=params["error_mode"])
    except ValueError as exc:
        raise InputError(str(exc)) from exc
    result.add_figure(f"{f.stem}_co2rr", fig)
    return result
