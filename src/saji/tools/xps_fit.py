"""xps-fit: XPS のピークフィッティング結果 CSV を図示する（スペクトル/合成/背景/各ピーク/残差）。"""

from __future__ import annotations

import json
from typing import Any

from ..core.plot import STYLE_PARAM, get_style
from ..core.tool import FileInput, InputError, InputFile, Param, Result, Tool
from ..techniques.xps import DEFAULT_OFFSET_STEP, DEFAULT_XLABEL, DEFAULT_YLABEL
from ..techniques.xps import fit as xf

# settings（JSON）で使えるキー。パラメータにあるものはパラメータで指定する。
SETTINGS_KEYS = {
    "labels": "主成分の凡例名 {spectrum/composite/background/residual: 名前}",
    "colors": "主成分の色 {spectrum/composite/background/residual: 色}",
    "show_spectrum": "生スペクトルを描くか", "show_composite": "合成曲線を描くか",
    "show_background": "背景を描くか", "show_peaks": "ピークを描くか",
    "peak_legend": "ピークを凡例に載せるか（既定は annotate_peaks の逆）",
    "peak_annotate_offsets": "ピーク注釈のずらし量 [dx, dy]（px、dy は上向きが正、null は自動）。"
                             "列順のリストか 列名→値 の dict",
    "annotate_headroom": "注釈用に y 上端を広げる比率（既定 0.2）",
    "annotate_on": "overlay でピーク注釈を付ける段 top / bottom / all / 番号（既定 top）",
    "residual_gap": "残差を offset で置くときの余白（データ縦幅比、既定 0.08）",
    "residual_ratio": "残差パネルの高さ比（既定 0.28）",
    "residual_ylabel": "残差パネルの y 軸名",
    "residual_zero_line": "残差の 0 基準線を引くか（既定 true）",
    "baseline_guides": "overlay で段ごとの 0 基準線を引くか（既定 true）",
    "sample_labels": "overlay の段ラベル（リスト、または 見出し→名前 の dict）",
    "sample_label_pos": "段ラベルの位置 [x（軸幅の割合）, y（段の間隔に対する割合）]（既定 [0.02, 0.62]）",
    "sample_label_ha": "段ラベルの水平揃え left / right（既定は x>0.5 なら right）",
    "show_sample_labels": "段ラベルを描くか（既定 true）",
    "files": "ファイルごとの上書き {ファイル名: {title, peak_labels, peak_colors, ...}}",
}
# パラメータとして持っているキー（settings に書かれたらパラメータを使うよう案内する）
PARAM_KEYS = {"residual_mode": "residual", "fill_peaks": "fill_peaks", "peak_alpha": "peak_alpha",
              "peak_labels": "peak_labels", "peak_colors": "peak_colors",
              "annotate_peaks": "annotate_peaks", "markers": "markers", "xlabel": "xlabel",
              "ylabel": "ylabel", "titles": "titles", "title": "title",
              "show_yticks": "show_yticks", "legend_outside": "legend_outside",
              "offset_step": "offset_step"}
# kaiseki-tool にはあったが saji では使わないキー（matplotlib 固有の見た目）
DROPPED_KEYS = {"figsize", "dpi", "style_override", "legend_anchor_x"}
# files[名前] で上書きできるキー（パネル・段ごとに変えて意味があるもの）
FILE_KEYS = {"title", "peak_labels", "peak_colors", "peak_annotate_offsets", "labels", "colors",
             "show_spectrum", "show_composite", "show_background", "show_peaks", "peak_legend",
             "fill_peaks", "peak_alpha", "annotate_peaks", "residual_gap", "residual_ylabel",
             "residual_zero_line", "annotate_headroom"}

TOOL = Tool(
    name="xps-fit",
    summary="XPS のピークフィッティング結果CSVを図示する（スペクトル・合成・背景・各ピーク・残差）",
    description=(
        "1ファイル = 1スペクトルのフィット結果CSV（Energy, Spectrum, Composite spectrum, Background, "
        "Residual, [1/1], [2/1], …）を読む。列は名前で解決し、既知の列に当たらない数値列は"
        "すべてピークとして描く（ピークは背景との間を塗りつぶす）。"
        "既定は 1ファイル = 1パネルで縦に並べる。overlay にすると1つの軸に段で積む"
        "（段ごとに 0-1 正規化し、試料は段ラベルで区別する）。x軸は既定で反転。"
        "入力形式は docs/data-formats.md の『XPS フィット結果CSV』を参照。"
    ),
    inputs=[
        FileInput("fit", accept=[".csv"], multiple=True, help="フィット結果の CSV（1ファイル = 1スペクトル）"),
    ],
    params=[
        Param("overlay", bool, False, group="並べ方", label="1つの軸に積む",
              help="複数ファイルを1つの軸にオフセットで積む（オフなら1ファイル = 1パネルで縦に並べる）"),
        Param("offset_step", float, DEFAULT_OFFSET_STEP, group="並べ方", label="段の間隔",
              help="overlay のとき、n 段目を n×この値だけ持ち上げる"),
        Param("residual", choices=("auto", "offset", "panel", "none"), default="auto", group="並べ方",
              label="残差の置き場所",
              help="offset=データの下に平行移動 / panel=本体の上の細いパネル / none=描かない / "
                   "auto=パネルなら offset、overlay なら none"),
        Param("normalize", choices=("auto", "on", "off"), default="auto", group="並べ方",
              label="0-1 に正規化",
              help="表示範囲内の全成分を同じ変換で 0-1 にする（成分どうしの関係は保つ）。"
                   "auto=パネルなら off、overlay なら on"),
        Param("xlim", "range", None, unit="eV", group="軸", label="x範囲",
              help="表示する結合エネルギーの範囲（全パネル共通。例 526,538）"),
        Param("ylim", "range", None, group="軸", label="y範囲", help="y の範囲（全パネル共通）"),
        Param("axis_ranges", "json", None, group="軸", advanced=True, label="パネルごとの範囲（JSON）",
              help='パネルの順に [{"x_range": [下限, 上限], "y_range": [下限, 上限]}, ...]。'
                   "overlay では先頭だけを使う。xlim / ylim を指定するとそちらが優先"),
        Param("invert_x", bool, True, group="軸", label="x軸を反転", help="結合エネルギー軸を大→小にする"),
        Param("peak_labels", str, None, group="ピーク", label="ピークの名前",
              help='ピークの表示名を列の順にカンマ区切りで（例 "lattice O,OH"）。'
                   'JSON なら列名→名前の dict も可（例 {"[1/1]": "lattice O"}）'),
        Param("annotate_peaks", bool, False, group="ピーク", label="ピーク名を図中に書く",
              help="ピーク名を凡例ではなく頂点に引き出し線つきで書く"),
        Param("fill_peaks", bool, True, group="ピーク", label="ピークを塗る",
              help="各ピークと背景の間を塗りつぶす"),
        Param("peak_colors", str, None, group="ピーク", advanced=True, label="ピークの色",
              help="ピークの色を列の順にカンマ区切りで（例 #1e33ff,#00a24a）。JSON の dict も可"),
        Param("peak_alpha", float, xf.DEFAULT_PEAK_ALPHA, min=0, max=1, group="ピーク", advanced=True,
              label="塗りの濃さ", help="塗りつぶしの不透明度"),
        Param("markers", bool, False, group="図", label="データ点を打つ",
              help="生スペクトルにマーカーを付ける"),
        Param("title", str, None, group="図", label="タイトル",
              help="図のタイトル（1ファイルのパネル表示ならパネルの見出し）"),
        Param("titles", str, None, group="図", label="パネル・段の見出し",
              help="ファイルの順にカンマ区切りで（既定はファイル名。overlay では段ラベル）"),
        Param("xlabel", str, DEFAULT_XLABEL, group="図", advanced=True, label="x軸の名前",
              help="x軸のラベル（英語で）"),
        Param("ylabel", str, DEFAULT_YLABEL, group="図", advanced=True, label="y軸の名前",
              help="y軸のラベル（英語で）"),
        Param("show_yticks", bool, False, group="図", advanced=True, label="y目盛の数値",
              help="y軸の目盛の数値を出す（任意単位なので既定は出さない）"),
        Param("legend_outside", bool, True, group="図", advanced=True, label="凡例を軸の外に",
              help="凡例を軸の右外に出す（オフにすると軸内の右上）"),
        Param("settings", "json", None, group="図", advanced=True, label="細かい設定（JSON）",
              help="その他の見た目の設定。使えるキー: " + ", ".join(SETTINGS_KEYS)
                   + '。例 {"peak_annotate_offsets": [null, [-40, null]], "files": {"a.csv": {"title": "pH7"}}}'),
        STYLE_PARAM,
    ],
    packages=["numpy", "pandas"],
    plots=True,
    examples=[
        'saji xps-fit fit_O1s.csv --xlim 526,538 --peak-labels "lattice O,OH" --title "O 1s"',
        "saji xps-fit fit_pH7.csv fit_pH9.csv fit_pH11.csv --overlay --offset-step 1.3 --annotate-peaks",
        "saji xps-fit fit_pH7.csv fit_pH9.csv --residual panel",
    ],
)


# ============================================================ パラメータの解釈
def parse_list_or_json(name: str, value: str | None) -> Any:
    """``"a,b"`` → ``["a", "b"]``。``[`` か ``{`` で始まれば JSON として読む。"""
    if value is None:
        return None
    text = value.strip()
    if text.startswith(("[", "{")):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise InputError(f"{name} の JSON を読めません: {exc}") from exc
    return [v.strip() for v in text.split(",")]


def check_settings(spec: Any, result: Result) -> dict[str, Any]:
    """settings（JSON）を検証する。パラメータにあるキーは誤り、未知のキーは警告。"""
    if spec is None:
        return {}
    if not isinstance(spec, dict):
        raise InputError("settings は JSON のオブジェクト（{キー: 値}）にしてください")
    for key in spec:
        if key in PARAM_KEYS:
            raise InputError(f"settings の {key} はパラメータ {PARAM_KEYS[key]} で指定してください")
    out = {}
    for key, value in spec.items():
        if key in DROPPED_KEYS:
            result.warn(f"settings の {key} は saji では使いません（無視しました）")
        elif key not in SETTINGS_KEYS:
            result.warn(f"settings の {key} は未知のキーです（無視しました。使えるもの: {', '.join(SETTINGS_KEYS)}）")
        else:
            out[key] = value
    files = out.get("files")
    if files is not None:
        if not isinstance(files, dict) or not all(isinstance(v, dict) for v in files.values()):
            raise InputError('settings.files は {ファイル名: {キー: 値}} の形にしてください')
        for fname, fs in files.items():
            bad = sorted(set(fs) - FILE_KEYS)
            if bad:
                result.warn(f"settings.files[{fname}] の {', '.join(bad)} は使えません（無視しました）")
    return out


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
        item = {}
        for k in ("x_range", "y_range"):
            v = r.get(k)
            if v is not None and (not isinstance(v, (list, tuple)) or len(v) != 2
                                  or any(e is None for e in v)):
                raise InputError(f"axis_ranges の {k} は [下限, 上限] にしてください: {v}")
            item[k] = None if v is None else [float(v[0]), float(v[1])]
        ranges.append(item)
    while len(ranges) < n:
        ranges.append({"x_range": None, "y_range": None})
    if params["xlim"] is not None:
        lo, hi = params["xlim"]
        if lo is None or hi is None:
            raise InputError(f"xlim は下限と上限の両方を指定してください: {params['xlim']}")
        for r in ranges:
            r["x_range"] = [lo, hi]
    if params["ylim"] is not None:
        for r in ranges:
            r["y_range"] = list(params["ylim"])     # y は表示だけなので片側指定も可
    return ranges


def file_settings(settings: dict, f: InputFile) -> dict[str, Any]:
    """settings.files から、このファイルの上書き（ファイル名か拡張子なしの名前で引く）。"""
    files = settings.get("files") or {}
    fs = files.get(f.name, files.get(f.stem)) or {}
    return {k: v for k, v in fs.items() if k in FILE_KEYS}


# ============================================================ 実行
def run(inputs: dict[str, list[InputFile]], params: dict) -> Result:
    result = Result()
    st = get_style(params["style"])
    files = inputs["fit"]
    overlay = params["overlay"]
    settings = check_settings(params["settings"], result)

    mode = params["residual"]
    if mode == "auto":
        mode = "none" if overlay else "offset"
    normalize = {"on": True, "off": False}.get(params["normalize"], overlay)

    # 全体の設定（kaiseki-tool の settings に相当）。パラメータ → settings の順に重ねる。
    base: dict[str, Any] = {k: v for k, v in settings.items() if k != "files"}
    base.update(residual_mode=mode, fill_peaks=params["fill_peaks"],
                peak_alpha=params["peak_alpha"], annotate_peaks=params["annotate_peaks"])
    for key in ("peak_labels", "peak_colors"):
        value = parse_list_or_json(key, params[key])
        if value is not None:
            base[key] = value

    titles = [t.strip() for t in params["titles"].split(",")] if params["titles"] else []
    if params["title"] and len(files) == 1 and not overlay and not titles:
        titles = [params["title"]]
    ranges = resolve_axis_ranges(params, len(files))

    panels, summaries = [], []
    for i, f in enumerate(files):
        fs = file_settings(settings, f)
        ps = {**base, **{k: v for k, v in fs.items() if k != "title"}}
        ps["residual_mode"] = mode       # 残差の置き場所は図全体で1つ（軸の構成が決まるため）
        # 見出し: titles[i] > settings.files[名前].title > ファイル名（拡張子なし）
        title = titles[i] if i < len(titles) and titles[i] else str(fs.get("title") or f.stem)
        x_range = (ranges[0] if overlay else ranges[i])["x_range"]
        try:
            data = xf.load_fit_csv(f.data)
            prepared = xf.prepare_fit_traces(data, x_range=x_range, normalize=normalize, settings=ps)
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            result.warn(f"読み込みをスキップしました {f.name}: {exc}")
            prepared = None
        if prepared is not None and not prepared["main"]:
            result.warn(f"{f.name}: 表示範囲内にデータがありません")
        panels.append({"title": title, "prepared": prepared, "settings": ps, "file": f})
        if prepared is not None:
            peaks = [t for t in prepared["main"] if t["kind"] == "peak"]
            summaries.append({
                "file": f.name, "title": title, "n_points": int(len(prepared["main"][0]["x"]))
                if prepared["main"] else 0,
                "components": [t["kind"] for t in prepared["main"] if t["kind"] != "peak"],
                "peaks": [{"column": t["column"], "label": t["label"],
                           "apex_x": None if t["apex"] is None else t["apex"][0],
                           "apex_y": None if t["apex"] is None else t["apex"][1]} for t in peaks],
            })
            result.log(f"[{f.name}] ピーク {len(peaks)} 本: {', '.join(t['label'] for t in peaks)}")

    common = dict(invert_x=params["invert_x"], markers=params["markers"], xlabel=params["xlabel"],
                  ylabel=params["ylabel"], show_yticks=params["show_yticks"],
                  legend_outside=params["legend_outside"])
    if overlay:
        ok = [p for p in panels if p["prepared"] is not None]
        if not ok:
            raise InputError("描けるファイルがありません")
        layers = xf.stack_layers([p["prepared"] for p in ok], offset_step=params["offset_step"],
                                 annotate_on=settings.get("annotate_on"))
        for i, (layer, p) in enumerate(zip(layers, ok)):
            layer["label"] = xf.pick(settings.get("sample_labels"), p["title"], i, p["title"])
        fig = xf.fit_overlay_figure(layers, st, fig_title=params["title"],
                                    x_range=ranges[0]["x_range"], y_range=ranges[0]["y_range"],
                                    offset_step=params["offset_step"], settings=settings, **common)
    else:
        if not any(p["prepared"] and p["prepared"]["main"] for p in panels):
            result.warn("描けるデータが1本もありません")
        fig = xf.fit_panels_figure(panels, st, fig_title=params["title"], axis_ranges=ranges,
                                   residual_mode=mode,
                                   residual_ratio=float(settings.get("residual_ratio",
                                                                     xf.DEFAULT_RESIDUAL_RATIO)),
                                   **common)
    result.add_figure("xps_fit", fig)
    result.data["files"] = summaries
    result.data["residual_mode"] = mode
    result.data["normalize"] = normalize
    return result
