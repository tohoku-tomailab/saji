"""mpt-cycle: EC-Lab の .mpt から指定サイクルを抜き出し、必要なら RHE 基準の電位を足す。CV を重ね描きする。"""

from __future__ import annotations

import math
from pathlib import PurePosixPath

from ..core.plot import STYLE_PARAM, get_style
from ..core.tool import FileInput, InputError, InputFile, Param, Result, Tool
from ..techniques import eclab

REFERENCE_CHOICES = (*eclab.REFERENCES, "custom")

TOOL = Tool(
    name="mpt-cycle",
    summary="EC-Lab の .mpt から指定サイクルを抜き出し、RHE 基準の電位を足した CSV と CV の重ね描きを出す",
    description=(
        "Bio-Logic EC-Lab の ASCII .mpt（1行目が EC-Lab ASCII FILE）から、cycle number が cycle の行だけを "
        "<名前>_cycle<N>_RHE.csv（rhe=false なら <名前>_cycle<N>.csv。1.5 は cycle1p5）に出す。"
        "列と値は元のまま（全欄をダブルクォートで囲む・UTF-8 BOM 付き・CRLF）。"
        "rhe=true なら末尾に E_RHE/V = Ewe + E(ref vs SHE) + (RT ln10 / F) × pH を足す（pH は必須）。"
        "参照電極のプリセットは 25 ℃付近のよく使う値なので、内部液の濃度・温度に合う値かを必ず確かめ、"
        "違えば ref_potential で指定する。"
        "同じデータで CV を1つの図に重ねる（既定は x=E_RHE/V か Ewe/V、y=I/mA か <I>/mA）。"
        "ファイルは渡した順に処理する。入力形式は docs/data-formats.md の『EC-Lab ASCII .mpt』を参照。"
    ),
    inputs=[
        FileInput("mpt", accept=[".mpt"], multiple=True,
                  help="EC-Lab の ASCII .mpt（バイナリの .mpr は不可）"),
    ],
    params=[
        Param("cycle", float, 2, group="抽出", label="サイクル",
              help="抜き出す cycle number（既定は2周目）"),
        Param("rhe", bool, True, group="RHE 変換", label="RHE に換算する",
              help="E_RHE/V 列を足す（オフなら指定サイクルの行だけを出す）"),
        Param("ph", float, None, min=0, max=eclab.PH_MAX, group="RHE 変換", label="pH",
              help="電解液の pH（RHE に換算するときは必須。例 14 / 7.4）"),
        Param("reference", choices=REFERENCE_CHOICES, default="hg-hgo-1m-koh", group="RHE 変換",
              label="参照電極",
              help=("E vs SHE のプリセット: hg-hgo-1m-koh=Hg/HgO (1 M KOH) 0.105 V / "
                    "ag-agcl-sat-kcl=Ag/AgCl (sat. KCl) 0.197 V / ag-agcl-3m-kcl=Ag/AgCl (3 M KCl) 0.210 V / "
                    "sce=SCE 0.244 V / custom=ref_potential で指定")),
        Param("ref_potential", float, None, unit="V", group="RHE 変換", label="E(ref vs SHE)",
              help="参照電極の電位（SHE 基準）。指定するとプリセットより優先する（custom では必須）"),
        Param("temperature", float, 25.0, unit="°C", group="RHE 変換", label="温度",
              help="(RT ln10 / F) の T に使う温度"),
        Param("x", str, None, group="図", label="x 軸の列",
              help="x 軸に使う列名（未指定ならファイルごとに E_RHE/V → Ewe/V → <Ewe>/V の順で見つかったもの）"),
        Param("y", str, None, group="図", label="y 軸の列",
              help="y 軸に使う列名（未指定ならファイルごとに I/mA → <I>/mA → I/A → <I>/A → I/µA … の順で見つかったもの）"),
        Param("xlim", "range", None, group="図", label="x の範囲", help="x 軸の範囲（例 0.9,1.8）"),
        Param("ylim", "range", None, group="図", label="y の範囲", help="y 軸の範囲（例 -5,20）"),
        Param("title", str, None, group="図", label="タイトル", help="図のタイトル（英語）"),
        Param("xlabel", str, None, group="図", advanced=True, label="x 軸名",
              help="x 軸名（未指定なら列名から。E_RHE/V → \"E / V vs. RHE\"、Ewe/V → \"E / V\"）"),
        Param("ylabel", str, None, group="図", advanced=True, label="y 軸名",
              help="y 軸名（未指定なら列名から。<I>/mA → \"I / mA\"）"),
        Param("legend", choices=("inside", "outside", "none"), default="inside", group="図",
              label="凡例", help="inside=軸内の右上 / outside=軸の右外 / none=出さない"),
        Param("traces", "json", None, group="図", advanced=True, label="ファイルごとの指定",
              help=("図に描くファイルと凡例名・色。[{\"file\": \"a.mpt\", \"label\": \"1st\", "
                    "\"color\": \"#ff1e1e\"}, ...]。file は入力のファイル名で照合し、この並び順で描く"
                    "（ここに無いファイルは図に描かない。CSV は出す）。label / color は省略可")),
        STYLE_PARAM,
    ],
    plots=True,
    examples=[
        "saji mpt-cycle data/ --ph 14",
        "saji mpt-cycle a.mpt b.mpt --cycle 3 --ph 7.4 --reference ag-agcl-sat-kcl",
        "saji mpt-cycle a.mpt --no-rhe --x Ewe/V",
        "saji mpt-cycle data/ --ph 14 --traces @traces.json   # 図に描くファイル・凡例名・色",
    ],
)


def _ref_potential(params: dict, result: Result) -> float:
    ref, value = params["reference"], params["ref_potential"]
    if value is not None:
        if ref != "custom" and value != eclab.REFERENCES[ref]:
            result.log(f"ref_potential={value} V を使いました（プリセット {ref} の {eclab.REFERENCES[ref]} V ではなく）")
        return value
    if ref == "custom":
        raise InputError("reference=custom のときは ref_potential（参照電極の SHE 基準の電位 / V）を指定してください")
    return eclab.REFERENCES[ref]


def _trace_specs(spec) -> list[dict]:
    """traces パラメータを検証して [{file, label, color}, ...] にする。"""
    if not isinstance(spec, list):
        raise InputError("traces は [{\"file\": ..., \"label\": ..., \"color\": ...}, ...] の形にしてください")
    out = []
    for i, e in enumerate(spec):
        if not isinstance(e, dict) or not e.get("file"):
            raise InputError(f"traces の {i + 1} 番目に file（ファイル名）がありません: {e!r}")
        out.append({"file": PurePosixPath(str(e["file"]).replace("\\", "/")).name,
                    "label": None if e.get("label") is None else str(e["label"]),
                    "color": None if e.get("color") is None else str(e["color"])})
    return out


def _plot_entries(done: list[dict], traces, result: Result) -> list[dict]:
    """図に描く順の [{item, label, color}]。traces なしなら処理した順、ありなら traces の順。"""
    if traces is None:
        return [{"item": d, "label": d["stem"], "color": None} for d in done]
    by_name: dict[str, dict] = {}
    for d in done:
        by_name.setdefault(d["source"], d)
    entries, used = [], set()
    for e in _trace_specs(traces):
        d = by_name.get(e["file"])
        if d is None:
            result.warn(f"traces のファイルが、処理できた入力にありません: {e['file']}")
            continue
        used.add(e["file"])
        entries.append({"item": d, "label": e["label"] if e["label"] is not None else d["stem"],
                        "color": e["color"]})
    unused = [d["source"] for d in done if d["source"] not in used]
    if unused:
        result.log(f"traces に無いので図に描かなかったファイル: {', '.join(unused)}")
    return entries


def run(inputs: dict[str, list[InputFile]], params: dict) -> Result:
    result = Result()
    st = get_style(params["style"])
    cycle, rhe = params["cycle"], params["rhe"]
    ph, temp_c = params["ph"], params["temperature"]
    ref = math.nan
    if rhe:
        if ph is None:
            raise InputError("RHE に換算するには ph を指定してください（換算しないなら --no-rhe）")
        if temp_c <= -273.15:
            raise InputError("temperature は絶対零度（-273.15 °C）より高くしてください")
        ref = _ref_potential(params, result)
        slope = eclab.ph_slope(temp_c)
        result.log(f"E_RHE = E_measured + {eclab.format_g10(ref)} + {slope:.5f} × pH"
                   f"（pH={eclab.js_number(ph)} → pH 項 {slope * ph:.4f} V）")

    done: list[dict] = []
    failed: list[str] = []
    names: set[str] = set()
    for f in inputs["mpt"]:
        try:
            ex = eclab.extract(eclab.decode(f.data), cycle=cycle, rhe=rhe, ph=ph,
                               ref_vs_she=ref, temp_c=temp_c)
        except ValueError as exc:
            result.warn(f"{f.name} を飛ばしました: {exc}")
            failed.append(f.name)
            continue
        out = eclab.output_name(f.name, cycle, rhe)
        if out in names:
            result.warn(f"出力ファイル名が重なったので上書きしました: {out}")
        names.add(out)
        result.add_file(out, eclab.BOM + ex.csv)
        result.log(f"{f.name} → {out}（{ex.rows} 行）")
        done.append({"source": f.name, "stem": eclab.base_name(f.name), "output": out, "ex": ex})
    if not done:
        raise InputError(f"処理できたファイルがありません（{len(failed)} 件とも失敗。警告を参照）")

    result.data["files"] = [{"source": d["source"], "output": d["output"], "rows": d["ex"].rows}
                            for d in done]
    result.data["failed"] = failed
    result.data["cycle"] = cycle
    if rhe:
        result.data["rhe"] = {"ph": ph, "ref_vs_she": ref, "temperature": temp_c,
                              "slope": eclab.ph_slope(temp_c),
                              "offset": ref + eclab.ph_slope(temp_c) * ph}

    # ---- 図（列はファイルごとに選ぶ。EC-Lab は測定法によって I/mA と <I>/mA のように列名が違うため）
    for key in ("x", "y"):
        want = params[key]
        if want and all(eclab.find_column(d["ex"].columns, [want]) < 0 for d in done):
            raise InputError(f"列 {want!r} がどのファイルにもありません"
                             f"（列の例: {', '.join(done[0]['ex'].columns)}）")
    series = []
    for e in _plot_entries(done, params["traces"], result):
        d = e["item"]
        try:
            x_col = eclab.pick_column(d["ex"].columns, params["x"], eclab.X_CANDIDATES, 0)
            y_col = eclab.pick_column(d["ex"].columns, params["y"], eclab.Y_CANDIDATES, 1)
        except ValueError as exc:
            result.warn(f"{d['source']} は図に描きませんでした: {exc}")
            continue
        x, y = eclab.series_xy(d["ex"].points, x_col, y_col)
        if not x:
            result.warn(f"{d['source']} には {x_col} と {y_col} の両方が数値の行が無いので、図に描きませんでした")
            continue
        series.append({"label": e["label"], "color": e["color"], "x": x, "y": y,
                       "x_col": x_col, "y_col": y_col, "output": d["output"]})
    result.data["plot"] = {"series": [{"label": s["label"], "x": s["x_col"], "y": s["y_col"]}
                                      for s in series]}
    if not series:
        result.warn("図に描ける系列がないので、図は出しませんでした")
        return result
    for key, param in (("x_col", "xlabel"), ("y_col", "ylabel")):
        labels = dict.fromkeys(eclab.axis_label(s[key]) for s in series)
        if len(labels) > 1 and not params[param]:
            used = ", ".join(dict.fromkeys(s[key] for s in series))
            result.warn(f"図の {key[0]} 軸の列がファイルによって違います（{used}）。単位や基準が同じか確かめてください")
    fig = eclab.cv_figure(series, st, x_col=series[0]["x_col"], y_col=series[0]["y_col"],
                          title=params["title"], xlabel=params["xlabel"], ylabel=params["ylabel"],
                          xlim=params["xlim"], ylim=params["ylim"], legend=params["legend"])
    result.add_figure(eclab.figure_name([s["output"] for s in series], cycle, rhe), fig)
    return result

