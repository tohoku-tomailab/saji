"""xrd-overlay: 処理済みの XRD パターン（2列 .xy）を重ね描き（ウォーターフォール）する。"""

from __future__ import annotations

from pathlib import PurePosixPath

from ..core.plot import STYLE_PARAM, get_style
from ..core.tool import FileInput, InputError, InputFile, Param, Result, Tool
from ..techniques import xrd

TOOL = Tool(
    name="xrd-overlay",
    summary="処理済みの XRD パターン（.xy）を、オフセットを付けて重ね描きする",
    description=(
        "xrd-process が出す <名前>_processed.xy（2列: 2θ 強度）を複数読み、1つの軸に"
        "ずらして重ねた図 overlay を出す。既定はファイル名順で、先頭のファイルが最上段。"
        "他の装置の2列 .xy も重ねられる（入力形式は docs/data-formats.md の『2列 .xy』）。"
        "peaks にピーク表 JSON（xrd-process と同じ形 [[2θ, 物質名, マーカー, 色], ...]）を渡すと、"
        "各パターンでピークが立っている位置にマーカーを付け、最も高い位置に物質名を書く。"
        "ファイルごとのラベル・色・オフセットは traces で指定する。"
    ),
    inputs=[
        FileInput("xy", accept=[".xy"], multiple=True,
                  help="処理済みの2列 .xy（xrd-process の *_processed.xy など）"),
        FileInput("peaks", accept=[".json"], required=False,
                  help="ピーク表 JSON（[[2θ, 物質名, マーカー, 色], ...]。例 [[43.30, \"Cu(111)\", \"v\", \"tab:red\"]]）"),
    ],
    params=[
        Param("offset", str, "auto", group="重ね方", label="オフセット",
              help="\"auto\"（全パターンの最大レンジ × gap の等間隔）か、刻みの数値（例 50）"),
        Param("gap", float, xrd.OVERLAY_GAP, min=0, group="重ね方", label="間隔係数",
              help="offset=auto のときの間隔（最大レンジの何倍ずらすか）"),
        Param("bottom_up", bool, False, group="重ね方", label="先頭を最下段に",
              help="先頭のファイルを最下段に積む（既定は最上段）"),
        Param("normalize_each", bool, False, group="重ね方", label="各データを最大で規格化",
              help="重ねる前に各パターンを最大値で割る（y 軸名に [each max-normalized] が付く）"),
        Param("traces", "json", None, group="重ね方", advanced=True, label="ファイルごとの指定",
              help=("ファイルごとのラベル・色・オフセット。[{\"file\": \"a_processed.xy\", "
                    "\"label\": \"400 C\", \"color\": \"tab:red\", \"offset\": 0}, ...]。"
                    "file はファイル名で照合し、この並び順で描く（ここに無いファイルは描かない）。"
                    "label / color / offset は省略可（省略時は自動）")),
        Param("peaks_on", choices=("each", "top"), default="each", group="ピーク帰属",
              label="マーカーを付ける系列", help="each=ピークが見つかった全パターン / top=最も上のパターンだけ"),
        Param("peak_guides", bool, True, group="ピーク帰属", label="参照位置の縦線",
              help="ピーク表の位置に薄い縦の点線を引く"),
        Param("peak_tol", float, 0.3, min=0, unit="deg", group="ピーク帰属", advanced=True,
              label="一致とみなす幅", help="参照位置とピークの一致とみなす幅（±）"),
        Param("peak_prominence", float, None, min=0, group="ピーク帰属", advanced=True,
              label="検出閾値", help="ピーク検出の prominence 閾値（未指定ならノイズの 3σ）"),
        Param("cmap", choices=xrd.CMAPS, default="tab10", group="図", label="配色",
              help="系列の色（tab10 / tab20 は巡回。本数が足りなければ viridis に切り替える）"),
        Param("xlim", "range", None, unit="deg", group="図", label="2θ の範囲",
              help="x 軸の範囲（例 30,80）"),
        Param("title", str, None, group="図", label="タイトル", help="図のタイトル（英語）"),
        Param("xlabel", str, None, group="図", advanced=True, label="x 軸名",
              help=f"x 軸名（未指定なら \"{xrd.XLABEL}\"）"),
        Param("ylabel", str, None, group="図", advanced=True, label="y 軸名",
              help=f"y 軸名（未指定なら \"{xrd.OVERLAY_YLABEL}\"。normalize_each なら末尾に [each max-normalized]）"),
        Param("legend", choices=("inside", "outside", "none"), default="inside", group="図",
              label="凡例", help="inside=軸内の右上 / outside=軸の右外 / none=出さない"),
        STYLE_PARAM,
    ],
    packages=["numpy", "scipy"],
    plots=True,
    examples=[
        "saji xrd-overlay outputs/20260923_140312-xrd-process/ --peaks peaks.json",
        "saji xrd-overlay a_processed.xy b_processed.xy --offset 50 --bottom-up --xlim 30,80",
        "saji xrd-overlay out/ --traces @traces.json   # ファイルごとのラベル・色・オフセット",
    ],
)


def _offset(value: str) -> str | float:
    s = str(value).strip()
    if s.lower() == "auto":
        return "auto"
    try:
        return float(s)
    except ValueError:
        raise InputError(f"offset は \"auto\" か数値にしてください: {value!r}") from None


def _trace_specs(spec) -> list[dict]:
    """traces パラメータを検証して [{file, label, color, offset}, ...] にする。"""
    if not isinstance(spec, list):
        raise InputError("traces は [{\"file\": ..., \"label\": ..., \"color\": ..., \"offset\": ...}, ...] の形にしてください")
    out = []
    for i, e in enumerate(spec):
        if not isinstance(e, dict) or not e.get("file"):
            raise InputError(f"traces の {i + 1} 番目に file（ファイル名）がありません: {e!r}")
        off = e.get("offset")
        if off is not None:
            try:
                off = float(off)
            except (TypeError, ValueError):
                raise InputError(f"traces の {i + 1} 番目の offset が数値ではありません: {off!r}") from None
        out.append({"file": str(e["file"]), "label": e.get("label"),
                    "color": None if e.get("color") is None else str(e["color"]), "offset": off})
    return out


def _entries(files: list[InputFile], traces, result: Result) -> list[dict]:
    """描く順の [{file, label, color, offset}, ...]。

    traces なし: ファイル名順。traces あり: traces の順で、ファイル名（パスなら最後の部分）で照合。
    """
    ordered = sorted(files, key=lambda f: f.name)
    if traces is None:
        return [{"file": f, "label": f.stem, "color": None, "offset": None} for f in ordered]
    by_name: dict[str, InputFile] = {}
    for f in ordered:
        by_name.setdefault(f.name, f)
    entries, used = [], set()
    for e in _trace_specs(traces):
        name = PurePosixPath(e["file"].replace("\\", "/")).name
        f = by_name.get(name)
        if f is None:
            result.warn(f"traces のファイルが入力にありません: {e['file']}")
            continue
        used.add(name)
        entries.append({"file": f, "label": e["label"] if e["label"] is not None else f.stem,
                        "color": e["color"], "offset": e["offset"]})
    unused = [f.name for f in ordered if f.name not in used]
    if unused:
        result.warn(f"traces に無いので描かなかったファイル: {', '.join(unused)}")
    return entries


def run(inputs: dict[str, list[InputFile]], params: dict) -> Result:
    result = Result()
    st = get_style(params["style"])
    offset = _offset(params["offset"])

    peaks = None
    if inputs.get("peaks"):
        try:
            peaks = xrd.load_peaks(inputs["peaks"][0].data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise InputError(f"ピーク表を読めません: {exc}") from exc

    traces = []
    for e in _entries(inputs["xy"], params["traces"], result):
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

    fig, info = xrd.overlay_figure(
        traces, st, offset=offset, gap=params["gap"], cmap=params["cmap"],
        normalize_each=params["normalize_each"], bottom_up=params["bottom_up"],
        peaks=peaks, peak_tol=params["peak_tol"], peak_prominence=params["peak_prominence"],
        peak_guides=params["peak_guides"], peaks_on=params["peaks_on"],
        title=params["title"], xlim=params["xlim"], xlabel=params["xlabel"],
        ylabel=params["ylabel"], legend=params["legend"])
    result.add_figure("overlay", fig)

    if info["cmap"] != params["cmap"]:
        result.log(f"{params['cmap']} では色が足りない（{len(traces)}本）ので {info['cmap']} を使いました")
    result.log(f"オフセット刻み step={info['step']:.4g}  cmap={info['cmap']}  {len(traces)}本")
    for m in info["peaks_missed"]:
        pos = next(p[0] for p in peaks if p[1] == m)
        result.log(f"ピーク未検出（どのパターンにも無い）: {m} ({pos}°)")

    result.data["step"] = info["step"]
    result.data["cmap"] = info["cmap"]
    result.data["traces"] = [
        {"file": t["file"], "label": ti["label"], "color": ti["color"], "offset": ti["offset"],
         "n_points": ti["n_points"],
         "peaks_found": [{"material": p["material"], "x": p["x"], "y": p["y"]}
                         for p in ti["peaks"] if p["found"]],
         "peaks_missed": [p["material"] for p in ti["peaks"] if not p["found"]]}
        for t, ti in zip(traces, info["traces"])
    ]
    result.data["peaks_missed"] = info["peaks_missed"]
    result.data["labels"] = info["labels"]
    return result
