"""xps-plot: 抽出済みの XPS スペクトル（x,y CSV）をオフセット付きで重ね描きする。"""

from __future__ import annotations

from typing import Any

from ..core.plot import STYLE_PARAM, get_style
from ..core.tool import FileInput, InputError, InputFile, Param, Result, Tool
from ..techniques.xps import DEFAULT_OFFSET_STEP, DEFAULT_XLABEL, DEFAULT_YLABEL
from ..techniques.xps import plot as xp

TOOL = Tool(
    name="xps-plot",
    summary="抽出済みの XPS スペクトル（x,y CSV）をオフセット付きで重ね描きする",
    description=(
        "1グループ = 1パネルで、グループ内のCSVを offset_step ずつ持ち上げて重ねる。"
        "既定は全ファイルを1グループ。group_by=region ならファイル名の末尾（sampleA_C1s.csv の C1s）"
        "ごとにパネルを分ける。細かく決めるときは groups（JSON）を使う。"
        "x軸（結合エネルギー）は既定で反転。xlim を指定すると、その範囲内で y を 0-1 に"
        "再正規化する（window_normalize）。入力は xps-extract の出力（docs/data-formats.md の"
        "『XPS 抽出CSV』）。"
    ),
    inputs=[
        FileInput("csv", accept=[".csv"], multiple=True,
                  help="x,y の CSV（xps-extract の出力。列名が x,y でなければ先頭2列）"),
    ],
    params=[
        Param("group_by", choices=("none", "region"), default="none", group="グループ",
              label="パネルの分け方",
              help="none=全ファイルを1枚に重ねる / region=ファイル名末尾の領域名（_C1s など）ごとに1パネル"),
        Param("groups", "json", None, group="グループ", advanced=True, label="グループの指定（JSON）",
              help='パネルごとのファイルの並び（2次元リスト）。要素はファイル名か '
                   '{"file": 名前, "label": 凡例名, "color": "#rrggbb"}。'
                   '例 [["a_Survey.csv", "b_Survey.csv"], [{"file": "a_C1s.csv", "label": "A"}]]。'
                   "指定すると group_by より優先"),
        Param("xlim", "range", None, unit="eV", group="軸", label="x範囲",
              help="表示する結合エネルギーの範囲（全パネル共通。例 188,192）"),
        Param("ylim", "range", None, group="軸", label="y範囲", help="y の範囲（全パネル共通）"),
        Param("axis_ranges", "json", None, group="軸", advanced=True, label="パネルごとの範囲（JSON）",
              help='パネルの順に [{"x_range": [下限, 上限], "y_range": [下限, 上限]}, ...]。'
                   "xlim / ylim を指定するとそちらが全パネルで優先"),
        Param("window_normalize", bool, True, group="軸", label="範囲内で再正規化",
              help="表示x範囲内のデータだけで y を 0-1 に正規化し直す"),
        Param("invert_x", bool, True, group="軸", label="x軸を反転", help="結合エネルギー軸を大→小にする"),
        Param("offset_step", float, DEFAULT_OFFSET_STEP, group="図", label="重ねる間隔",
              help="n 本目を n×この値だけ持ち上げる"),
        Param("markers", bool, False, group="図", label="データ点を打つ", help="データ点にマーカーを付ける"),
        Param("title", str, None, group="図", label="タイトル",
              help="図のタイトル（1グループのときはパネルの見出し。既定はファイル名の末尾）"),
        Param("titles", str, None, group="図", advanced=True, label="パネルの見出し",
              help="パネルごとの見出しをカンマ区切りで（既定は各グループ先頭ファイル名の末尾）"),
        Param("xlabel", str, DEFAULT_XLABEL, group="図", advanced=True, label="x軸の名前",
              help="x軸のラベル（英語で）"),
        Param("ylabel", str, DEFAULT_YLABEL, group="図", advanced=True, label="y軸の名前",
              help="y軸のラベル（英語で）"),
        Param("show_yticks", bool, False, group="図", advanced=True, label="y目盛の数値",
              help="y軸の目盛の数値を出す（任意単位なので既定は出さない）"),
        Param("legend_outside", bool, True, group="図", advanced=True, label="凡例を軸の外に",
              help="凡例を軸の右外に出す（オフにすると軸内の右上）"),
        STYLE_PARAM,
    ],
    packages=["numpy", "pandas"],
    plots=True,
    examples=[
        "saji xps-plot out/*_Survey.csv --xlim 188,192 --markers --title Survey",
        "saji xps-plot out/ --group-by region",
    ],
)


def _file_index(files: list[InputFile]) -> dict[str, InputFile]:
    """ファイル名（拡張子あり・なし）→ 入力ファイル。同名は先のものを使う。"""
    out: dict[str, InputFile] = {}
    for f in files:
        out.setdefault(f.name, f)
        out.setdefault(f.stem, f)
    return out


def _entry(f: InputFile, label: Any = None, color: Any = None) -> dict[str, Any]:
    return {"name": f.name, "data": f.data, "label": str(label) if label else f.stem,
            "color": str(color) if color else None}


def resolve_groups(files: list[InputFile], params: dict, result: Result) -> list[list[dict[str, Any]]]:
    """入力ファイルとパラメータから、パネルごとの entry の並びを決める。"""
    spec = params["groups"]
    if spec is None:
        if params["group_by"] == "region":
            by_region: dict[str, list[dict[str, Any]]] = {}
            for f in files:
                by_region.setdefault(xp.region_of(f.name), []).append(_entry(f))
            return list(by_region.values())
        return [[_entry(f) for f in files]]

    if not isinstance(spec, list) or not all(isinstance(g, list) for g in spec):
        raise InputError("groups は2次元リスト（[[ファイル, ...], [ファイル, ...]]）にしてください")
    index = _file_index(files)
    used: set[str] = set()
    groups: list[list[dict[str, Any]]] = []
    for g in spec:
        entries = []
        for item in g:
            if isinstance(item, dict):
                name, label, color = item.get("file"), item.get("label"), item.get("color")
            else:
                name, label, color = item, None, None
            if not name:
                result.warn(f"groups の要素に 'file' がありません: {item}")
                continue
            f = index.get(str(name))
            if f is None:
                result.warn(f"groups のファイルが入力にありません: {name}")
                continue
            used.add(f.name)
            entries.append(_entry(f, label, color))
        groups.append(entries)
    unused = [f.name for f in files if f.name not in used]
    if unused:
        result.warn(f"groups に含まれていないので描かなかったファイル: {', '.join(unused)}")
    return groups


def resolve_axis_ranges(params: dict, n: int) -> list[dict[str, Any]]:
    """パネルごとの {"x_range", "y_range"}。xlim / ylim は全パネルに上書きする（kaiseki-tool と同じ）。"""
    spec = params["axis_ranges"] or []
    if not isinstance(spec, list) or not all(isinstance(r, dict) for r in spec):
        raise InputError('axis_ranges は [{"x_range": [下限, 上限], "y_range": [下限, 上限]}, ...] の形にしてください')
    ranges = []
    for r in spec:
        unknown = set(r) - {"x_range", "y_range"}
        if unknown:
            raise InputError(f"axis_ranges に使えないキーがあります: {sorted(unknown)}（x_range / y_range）")
        ranges.append({k: _range_value(k, r.get(k)) for k in ("x_range", "y_range")})
    while len(ranges) < n:
        ranges.append({"x_range": None, "y_range": None})
    if params["xlim"] is not None:
        for r in ranges:
            r["x_range"] = _full_range("xlim", params["xlim"])
    if params["ylim"] is not None:
        for r in ranges:
            r["y_range"] = list(params["ylim"])     # y は表示だけなので片側指定も可
    return ranges


def _range_value(key: str, value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 2 or any(v is None for v in value):
        raise InputError(f"axis_ranges の {key} は [下限, 上限] にしてください: {value}")
    return [float(value[0]), float(value[1])]


def _full_range(name: str, value: list) -> list[float]:
    """x の範囲はデータの切り出しにも使うので、両端を指定させる（kaiseki-tool も両端必須）。"""
    if value[0] is None or value[1] is None:
        raise InputError(f"{name} は下限と上限の両方を指定してください: {value}")
    return [float(value[0]), float(value[1])]


def split_titles(value: str | None) -> list[str]:
    return [] if not value else [v.strip() for v in value.split(",")]


def run(inputs: dict[str, list[InputFile]], params: dict) -> Result:
    result = Result()
    st = get_style(params["style"])
    groups = resolve_groups(inputs["csv"], params, result)
    if not any(groups):
        raise InputError("描けるファイルがありません")
    ranges = resolve_axis_ranges(params, len(groups))

    titles = split_titles(params["titles"])
    if params["title"] and len(groups) == 1 and not titles:
        titles = [params["title"]]
    titles = [titles[i] if i < len(titles) and titles[i] else xp.infer_group_title(g, i)
              for i, g in enumerate(groups)]

    prepared, summaries = [], []
    for gi, entries in enumerate(groups):
        traces, warns = xp.prepare_traces(entries, x_range=ranges[gi]["x_range"],
                                          window_normalize=params["window_normalize"],
                                          offset_step=params["offset_step"])
        for w in warns:
            result.warn(w)
        prepared.append(traces)
        result.log(f"[{titles[gi]}] {len(traces)} 本: {', '.join(t['name'] for t in traces)}")
        summaries.append({"title": titles[gi], "x_range": ranges[gi]["x_range"],
                          "files": [{"file": t["name"], "label": t["label"],
                                     "n_points": int(len(t["x"]))} for t in traces]})
    if not any(prepared):
        result.warn("描けるデータが1本もありません")

    fig = xp.plot_figure(prepared, st, titles=titles, fig_title=params["title"],
                         axis_ranges=ranges, invert_x=params["invert_x"], markers=params["markers"],
                         xlabel=params["xlabel"], ylabel=params["ylabel"],
                         show_yticks=params["show_yticks"], legend_outside=params["legend_outside"])
    result.add_figure("xps", fig)
    result.data["groups"] = summaries
    return result
