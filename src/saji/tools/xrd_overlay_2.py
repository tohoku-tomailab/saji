"""xrd-overlay-2: XRD パターンの重ね描きの下に、参照ピークを縦棒のパネルで並べる。

重ね方・図のパラメータは xrd-overlay と同じもの（同じ Param を使う）。違いは参照ピークの示し方で、
xrd-overlay はデータ上でピークを探してマーカーを付けるが、こちらは参照パネルに縦棒を描くだけ
（ピーク検出をしない）。
"""

from __future__ import annotations

from ..core.plot import get_style
from ..core.tool import FileInput, InputError, InputFile, Param, Result, Tool
from ..techniques import xrd
from . import xrd_overlay

_SHARED = {p.name: p for p in xrd_overlay.TOOL.params}

TOOL = Tool(
    name="xrd-overlay-2",
    summary="処理済みの XRD パターン（.xy）を重ね描きし、その下に参照ピークを縦棒で並べる",
    description=(
        "xrd-overlay と同じように2列 .xy を複数読み、オフセットを付けて重ねた図 overlay を出す。"
        "refs に参照ピーク JSON（1物質1ファイル。{\"name\", \"label\", \"peaks\": [{\"two_theta\", "
        "\"intensity\", \"hkl\"}, ...]}）を渡すと、図の下に参照1つにつき1パネルを並べ、参照ピークの"
        "位置に相対強度（最大 100）を高さにした縦棒を描く。データ上にマーカーは付けない。"
        "参照パネルは渡した順に上から並ぶ（CLI はフォルダならファイル名順、Web はファイル名順）。"
        "形式は docs/data-formats.md の『参照ピーク JSON』。"
    ),
    inputs=[
        FileInput("xy", accept=[".xy"], multiple=True,
                  help="処理済みの2列 .xy（xrd-process の *_processed.xy など）"),
        FileInput("refs", accept=[".json"], multiple=True, required=False,
                  help="参照ピーク JSON（1物質1ファイル。例 Cu.json, CuO.json）"),
    ],
    params=[
        *(_SHARED[k] for k in ("offset", "gap", "bottom_up", "normalize_each", "traces")),
        Param("ref_height", float, xrd.REF_PANEL_RATIO, min=0.05, max=1.0, group="参照ピーク",
              label="参照パネルの高さ",
              help="参照パネル1枚の高さ（上のパネルの高さに対する比）。パネルの分だけ図が縦に伸びる"),
        Param("ref_min_intensity", float, 0.0, min=0, max=100, group="参照ピーク",
              label="描く最小の強度", help="相対強度（最大 100）がこれ未満の縦棒は描かない"),
        *(_SHARED[k] for k in ("cmap", "xlim", "title", "xlabel", "ylabel", "show_yticks", "legend", "style")),
    ],
    packages=["numpy", "scipy"],
    plots=True,
    examples=[
        "saji xrd-overlay-2 outputs/20260923_140312-xrd-process/ --refs Cu.json Cu2O.json CuO.json",
        "saji xrd-overlay-2 a_processed.xy b_processed.xy --refs refs/ --xlim 30,80 --ref-min-intensity 5",
    ],
)


def run(inputs: dict[str, list[InputFile]], params: dict) -> Result:
    result = Result()
    st = get_style(params["style"])
    offset = xrd_overlay._offset(params["offset"])

    refs = []
    for f in inputs.get("refs") or []:
        try:
            refs += xrd.load_refs(f.data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise InputError(f"参照ピーク {f.name} を読めません: {exc}") from exc

    traces = []
    for e in xrd_overlay._entries(inputs["xy"], params["traces"], result):
        f = e["file"]
        try:
            x, y = xrd.load_xy(f.text())
        except ValueError as exc:
            result.warn(f"{f.name} を読めないので飛ばしました: {exc}")
            continue
        traces.append({"file": f.name, "label": str(e["label"]), "x": x, "y": y,
                       "color": e["color"], "offset": e["offset"]})
    if not traces:
        raise InputError("描けるデータがありません（2列の .xy を渡してください）")

    fig, info = xrd.overlay_ref_figure(
        traces, refs, st, ref_height=params["ref_height"],
        ref_min_intensity=params["ref_min_intensity"], xlim=params["xlim"],
        xlabel=params["xlabel"], offset=offset, gap=params["gap"], cmap=params["cmap"],
        normalize_each=params["normalize_each"], bottom_up=params["bottom_up"],
        title=params["title"], ylabel=params["ylabel"], legend=params["legend"],
        show_yticks=params["show_yticks"])
    result.add_figure("overlay", fig)

    if info["cmap"] != params["cmap"]:
        result.log(f"{params['cmap']} では色が足りない（{len(traces)}本）ので {info['cmap']} を使いました")
    result.log(f"オフセット刻み step={info['step']:.4g}  cmap={info['cmap']}  {len(traces)}本")
    for r in info["refs"]:
        result.log(f"参照 {r['name']}: {r['n_shown']}/{r['n_peaks']} 本を描画"
                   + (f"（{r['source']}）" if r["source"] else ""))
        if r["n_shown"] == 0:
            result.warn(f"参照 {r['name']} は x の範囲内に描ける線がありません")

    result.data["step"] = info["step"]
    result.data["cmap"] = info["cmap"]
    result.data["xlim"] = info["xlim"]
    result.data["traces"] = [
        {"file": t["file"], "label": ti["label"], "color": ti["color"], "offset": ti["offset"],
         "n_points": ti["n_points"]}
        for t, ti in zip(traces, info["traces"])
    ]
    result.data["refs"] = info["refs"]
    return result
