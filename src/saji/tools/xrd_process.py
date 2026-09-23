"""xrd-process: SmartLab の XRD パターンを前処理する（背景除去・平滑化・規格化・ピーク帰属）。"""

from __future__ import annotations

from ..core.plot import STYLE_PARAM, get_style
from ..core.tool import FileInput, InputError, InputFile, Param, Result, Tool
from ..techniques import xrd

TOOL = Tool(
    name="xrd-process",
    summary="SmartLab の XRD .TXT を前処理（背景除去・平滑化・規格化・ピーク帰属）する",
    description=(
        "処理順はビニング → 背景除去 → 平滑化 → 規格化。ファイルごとに処理済みの "
        "<名前>_processed.xy（2列: 2θ 強度）と図 <名前>_plot を出す。"
        "入力形式は docs/data-formats.md の『Rigaku SmartLab .TXT』を参照。"
        "peaks にピーク表 JSON（[[2θ, 物質名, マーカー, 色], ...]）を渡すと、"
        "ピークが立っている位置に帰属のマーカーを付ける。"
    ),
    inputs=[
        FileInput("raw", accept=[".txt"], multiple=True, help="SmartLab の .TXT"),
        FileInput("peaks", accept=[".json"], required=False,
                  help="ピーク表 JSON（[[2θ, 物質名, マーカー, 色], ...]。例 [[43.30, \"Cu(111)\", \"v\", \"tab:red\"]]）"),
    ],
    params=[
        Param("bin", int, None, min=1, group="前処理", help="N 点ずつ平均してビニングする（例 25。未指定ならしない）"),
        Param("bg", choices=("none", "arpls", "snip"), default="arpls", group="背景除去",
              help="背景除去の方法"),
        Param("lam", float, 1e6, min=0, group="背景除去", advanced=True, help="arPLS の滑らかさ"),
        Param("snip_window", int, 120, min=1, unit="点", group="背景除去", advanced=True,
              help="SNIP の最大半窓"),
        Param("snip_smooth", int, 3, min=0, unit="点", group="背景除去", advanced=True,
              help="SNIP の平滑半窓"),
        Param("smooth", choices=("none", "savgol", "moving_average", "gaussian"), default="none",
              group="平滑化", help="平滑化の方法"),
        Param("sg_window", int, 11, min=3, unit="点", group="平滑化", advanced=True,
              help="Savitzky-Golay の窓（偶数なら奇数に直す）"),
        Param("sg_poly", int, 3, min=0, group="平滑化", advanced=True, help="Savitzky-Golay の多項式次数"),
        Param("ma_window", int, 9, min=1, unit="点", group="平滑化", advanced=True, help="移動平均の窓"),
        Param("gauss_sigma", float, 2.0, min=0, unit="点", group="平滑化", advanced=True,
              help="ガウシアンの σ"),
        Param("norm", choices=("none", "max", "area", "reference"), default="none", group="規格化",
              help="規格化の方法（max=最大ピーク / area=積分強度 / reference=指定ピーク）"),
        Param("norm_target", float, 1.0, group="規格化", help="規格化後の目標値（100 で % 表示）"),
        Param("norm_ref_pos", float, None, unit="deg", group="規格化",
              help="reference 用: 基準ピークの 2θ（例 Cu(111) なら 43.3）"),
        Param("norm_ref_tol", float, 0.3, min=0, unit="deg", group="規格化", advanced=True,
              help="reference 用: 基準ピークを探す幅（±）"),
        Param("peak_tol", float, 0.3, min=0, unit="deg", group="ピーク帰属", advanced=True,
              help="参照位置とピークの一致とみなす幅（±）"),
        Param("peak_prominence", float, None, min=0, group="ピーク帰属", advanced=True,
              help="ピーク検出の prominence 閾値（未指定ならノイズの 3σ）"),
        Param("show_raw", bool, True, group="図", help="生データを重ねて描く"),
        STYLE_PARAM,
    ],
    packages=["numpy", "scipy", "pybaselines"],
    plots=True,
    examples=[
        "saji xrd-process data/xrd/ --bg arpls --smooth savgol --norm max --norm-target 100",
        "saji xrd-process sample.TXT --bin 25 --peaks peaks.json",
    ],
)


def _kwargs(p: dict) -> tuple[dict, dict, dict]:
    """パラメータから各処理の kwargs を組み立てる（kaiseki-tool と同じ組み方）。"""
    bg_kwargs: dict = {}
    if p["bg"] == "arpls":
        bg_kwargs["lam"] = p["lam"]
    elif p["bg"] == "snip":
        bg_kwargs["max_half_window"] = p["snip_window"]
        bg_kwargs["smooth_half_window"] = p["snip_smooth"]

    sm_kwargs: dict = {}
    if p["smooth"] == "savgol":
        sm_kwargs = {"window_length": p["sg_window"], "polyorder": p["sg_poly"]}
    elif p["smooth"] == "moving_average":
        sm_kwargs = {"window": p["ma_window"]}
    elif p["smooth"] == "gaussian":
        sm_kwargs = {"sigma": p["gauss_sigma"]}

    nm_kwargs: dict = {}
    if p["norm"] != "none":
        nm_kwargs["target"] = p["norm_target"]
    if p["norm"] == "reference":
        if p["norm_ref_pos"] is None:
            raise InputError("norm=reference には norm_ref_pos（基準ピークの 2θ）が必要です")
        nm_kwargs["ref_pos"] = p["norm_ref_pos"]
        nm_kwargs["ref_tol"] = p["norm_ref_tol"]
    return bg_kwargs, sm_kwargs, nm_kwargs


def run(inputs: dict[str, list[InputFile]], params: dict) -> Result:
    result = Result()
    st = get_style(params["style"])
    bg_kwargs, sm_kwargs, nm_kwargs = _kwargs(params)

    peaks = None
    if inputs.get("peaks"):
        try:
            peaks = xrd.load_peaks(inputs["peaks"][0].data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise InputError(f"ピーク表を読めません: {exc}") from exc

    summaries = []
    for f in inputs["raw"]:
        try:
            x, y, _meta = xrd.load_smartlab(f.text())
        except ValueError as exc:
            raise InputError(f"{f.name}: {exc}") from exc
        res = xrd.process(x, y, bin_factor=params["bin"], bg_method=params["bg"],
                          bg_kwargs=bg_kwargs, smooth_method=params["smooth"],
                          smooth_kwargs=sm_kwargs, norm_method=params["norm"],
                          norm_kwargs=nm_kwargs)
        result.log(f"[{f.name}] {len(res['x'])}点 bg={params['bg']} smooth={params['smooth']} "
                   f"norm={params['norm']} bin={params['bin']}")
        info = res["norm_info"]
        if info.get("skipped"):
            result.warn(f"{f.name}: 規格化のスケールが 0 / 無効なので規格化しませんでした（{params['norm']}）")
        elif params["norm"] != "none":
            at = f" @ {info['at']:.2f}deg" if "at" in info else ""
            result.log(f"  規格化 {params['norm']}: scale={res['norm_scale']:.3g}{at} -> target={info['target']}")

        result.add_file(f"{f.stem}_processed.xy", xrd.format_xy(res))
        fig, found = xrd.process_figure(
            res, st, title=f.name, peaks=peaks, show_raw=params["show_raw"],
            peak_tol=params["peak_tol"], peak_prominence=params["peak_prominence"])
        result.add_figure(f"{f.stem}_plot", fig)
        missed = [p["material"] for p in found if not p["found"]]
        if missed:
            result.log(f"  ピーク未検出（マークなし）: {', '.join(missed)}")
        summaries.append({
            "file": f.name, "n_points": int(len(res["x"])),
            "norm_scale": res["norm_scale"], "norm_at": info.get("at"),
            "peaks_found": [p["material"] for p in found if p["found"]],
            "peaks_missed": missed,
        })
    result.data["files"] = summaries
    return result
