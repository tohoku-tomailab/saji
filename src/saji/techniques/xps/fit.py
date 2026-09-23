"""XPS ピークフィッティング結果CSVの図示（xps-fit）。

CasaXPS/Multipak 等が吐く「1ファイル = 1スペクトルのフィット結果」CSV
（例: ``Energy, Spectrum, Composite spectrum, Background, Residual, [1/1], [2/1]``）
を読み、生スペクトル・合成曲線・バックグラウンド・各ピーク（塗りつぶし）・残差を描く。

列は**名前で解決**する（列順・別名・欠落に強い）。既知の論理列に当たらなかった
数値列はすべて「フィッティングに使った個別ピーク」として扱うので、ピーク数が
いくつでも、列名が ``[1/1]`` でも ``O 1s A`` でもそのまま描ける。

ピーク列・合成曲線はバックグラウンドを含んだ値（装置出力の慣習）として扱い、
塗りつぶしは「バックグラウンド ⇔ ピーク曲線」の間を塗る。

読み込みと前処理（load_fit_csv / prepare_fit_traces / shift_prepared）は kaiseki-tool の
xps/fit.py と同じ数値になるようにしてある。図は Plotly の形式で組み立てる:
  - 1ファイル = 1パネル（縦に並べる）/ overlay=True なら1つの軸に段で積む
  - 残差は offset（データの下に平行移動）/ panel（本体の上の細いパネル）/ none
  - ピーク注釈は頂点を矢印で指し、文字は「その x で一番上の曲線」より上に置く
    （持ち上げる量は軸範囲と図の大きさから px に換算する）
"""

from __future__ import annotations

import io
from typing import Any, Mapping, Sequence

import numpy as np

from ...core.plot import add_annotation, add_hline, add_line, new_figure, panel_domains, set_axis
from ...core.plot.style import to_rgba
from ...core.tableio import decode_text, resolve_columns, split_row
from . import DEFAULT_OFFSET_STEP, DEFAULT_XLABEL, DEFAULT_YLABEL

# 論理名 -> 列名の別名候補（正規化して照合するので大文字小文字・記号差は無視される）。
FIT_COLUMNS: dict[str, list[str]] = {
    "energy": ["Energy", "B.E.", "BE", "Binding Energy", "eV", "x"],
    "spectrum": ["Spectrum", "Raw", "Raw data", "Data", "Intensity", "CPS", "y"],
    "composite": ["Composite spectrum", "Composite", "Envelope", "Fit",
                  "Fitted", "Sum", "Total"],
    "background": ["Background", "BG", "Baseline"],
    "residual": ["Residual", "Residuals", "Difference", "Diff"],
}

# 成分ごとの既定の見た目。width は style["line"] に対する倍率。
COMPONENT_LABELS = {
    "spectrum": "Spectrum",
    "composite": "Composite",
    "background": "Background",
    "residual": "Residual",
}
COMPONENT_COLORS = {
    "spectrum": "#111111",
    "composite": "#ff1e1e",
    "background": "#7f7f7f",
    "residual": "#555555",
}
COMPONENT_DASH = {
    "spectrum": "-", "composite": "-", "background": "--", "residual": "-",
}
COMPONENT_WIDTH = {
    "spectrum": 1.0, "composite": 1.0, "background": 0.75, "residual": 0.6,
}
PEAK_WIDTH = 0.7

# ピーク色（生データの黒・合成の赤とかぶらない色から始める）。
PEAK_COLORS = [
    "#1e33ff", "#00a24a", "#9b34eb", "#00a8c6", "#ff8c1a", "#c2185b",
    "#5d8aa8", "#7a6a00", "#8b4513", "#2f9e44",
]

# 残差の置き場所（residual_mode）。
RESIDUAL_MODES = ("offset", "panel", "none")

DEFAULT_RESIDUAL_GAP = 0.08     # 残差をデータ下に置くときの余白（データ縦幅比）
DEFAULT_RESIDUAL_RATIO = 0.28   # 残差を別パネルにするときの高さ比
DEFAULT_PEAK_ALPHA = 0.25
DEFAULT_ANNOTATE_HEADROOM = 0.2  # ピーク注釈を置くために y 上端を広げる比率
DEFAULT_SAMPLE_LABEL_POS = (0.02, 0.62)
PANEL_GAP_PX = 130              # パネル間の空き（見出し + 上のパネルの x 軸名が入る分）
RESIDUAL_GAP_PX = 6             # 残差パネルと本体の隙間（ほぼ密着）

_DASH = {"-": "solid", "--": "dash", ":": "dot", "-.": "dashdot"}


# ============================================================ 読み込み
def _find_header_row(lines: Sequence[str], max_scan: int = 200) -> int:
    """エネルギー列 + 何かのy列を含む行（ヘッダ行）の行番号。無ければ 0。

    前段に測定条件ヘッダが付いたCSVでもデータ表の先頭を追従できる。
    """
    for i, line in enumerate(lines[:max_scan]):
        cols = resolve_columns(split_row(line), FIT_COLUMNS)
        if "energy" in cols and any(
            k in cols for k in ("spectrum", "composite", "background")
        ):
            return i
    return 0


def load_fit_csv(data: bytes) -> dict[str, Any]:
    """フィット結果CSVを読み、成分ごとの配列に分解する。

    戻り値は ``x`` / ``spectrum`` / ``composite`` / ``background`` / ``residual`` /
    ``peaks``（``[{"name": 列名, "y": 配列}, ...]``）。無い成分は None。
    residual が無くても spectrum と composite があれば差分から補う。
    """
    import pandas as pd

    text = decode_text(data)
    lines = text.splitlines()
    df = pd.read_csv(io.StringIO(text), skiprows=_find_header_row(lines), engine="python")
    df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed")]]
    df = df.dropna(axis=1, how="all")

    cols = resolve_columns(list(df.columns), FIT_COLUMNS, required=["energy"])

    def column(index: int) -> np.ndarray:
        return pd.to_numeric(df.iloc[:, index], errors="coerce").to_numpy(dtype=float)

    x = column(cols["energy"])
    keep = np.isfinite(x)

    def take(name: str) -> np.ndarray | None:
        if name not in cols:
            return None
        return column(cols[name])[keep]

    peaks: list[dict[str, Any]] = []
    used = set(cols.values())
    for i, name in enumerate(df.columns):
        if i in used:
            continue
        y = column(i)[keep]
        if not np.any(np.isfinite(y)):
            continue
        peaks.append(dict(name=str(name).strip(), y=y))

    spectrum, composite = take("spectrum"), take("composite")
    background, residual = take("background"), take("residual")
    if residual is None and spectrum is not None and composite is not None:
        residual = spectrum - composite       # 残差列が無ければ差分から作る
    if all(v is None for v in (spectrum, composite, background)) and not peaks:
        raise ValueError("スペクトル列が見つかりません")

    return dict(x=x[keep], spectrum=spectrum, composite=composite,
                background=background, residual=residual, peaks=peaks)


# ============================================================ 前処理
def pick(spec: Any, name: str, index: int, default: Any) -> Any:
    """dict（列名→値）/ list（列順）/ 未指定 のいずれでも1件取り出す。"""
    if isinstance(spec, Mapping):
        return spec.get(name, default)
    if isinstance(spec, Sequence) and not isinstance(spec, str):
        return spec[index] if index < len(spec) else default
    return default


def prepare_fit_traces(
    data: Mapping[str, Any],
    *,
    x_range: Sequence[float] | None = None,
    normalize: bool = False,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """load_fit_csv の結果を描画用トレース群へ変換する。

    表示x範囲でクリップ → （normalize 時）全成分を同一変換で 0-1 化 →
    成分ごとに色・線種・凡例名を決め、残差は residual_mode に応じて配置する。

    戻り値: ``main``（主成分トレースのリスト。凡例の並び順 = このリスト順）、
    ``residual``（残差トレース or None）、``residual_zero``（残差の0基準線 y）、
    ``mode``（採用した residual_mode）。
    """
    s = dict(settings or {})
    x = np.asarray(data["x"], dtype=float)
    keep = np.isfinite(x)
    if x_range is not None:
        lo, hi = min(x_range), max(x_range)
        keep &= (x >= lo) & (x <= hi)
    x = x[keep]

    mode = str(s.get("residual_mode", "offset")).lower()
    if mode not in RESIDUAL_MODES:
        raise ValueError(
            f"未知の residual_mode: {mode}（候補: {', '.join(RESIDUAL_MODES)}）")
    if len(x) == 0:
        return dict(main=[], residual=None, residual_zero=None, mode=mode)

    def take(key: str) -> np.ndarray | None:
        v = data.get(key)
        return None if v is None else np.asarray(v, dtype=float)[keep]

    spectrum, composite = take("spectrum"), take("composite")
    background, residual = take("background"), take("residual")
    peaks = [dict(name=p["name"], y=np.asarray(p["y"], dtype=float)[keep])
             for p in (data.get("peaks") or [])]

    # ---- 正規化: 表示窓内の全成分を同一の一次変換で 0-1 に寄せる ----
    # （成分どうしの相対関係が崩れないように、残差はスケールのみ適用する）
    if normalize:
        pool = [a for a in (spectrum, composite, background) if a is not None]
        pool += [p["y"] for p in peaks]
        if pool:
            allv = np.concatenate(pool)
            lo_v = float(np.nanmin(allv))
            span = float(np.nanmax(allv) - lo_v) or 1.0
            spectrum, composite, background = (
                None if a is None else (a - lo_v) / span
                for a in (spectrum, composite, background)
            )
            peaks = [dict(name=p["name"], y=(p["y"] - lo_v) / span) for p in peaks]
            residual = None if residual is None else residual / span

    labels = {**COMPONENT_LABELS, **(s.get("labels") or {})}
    colors = {**COMPONENT_COLORS, **(s.get("colors") or {})}
    fill_peaks = bool(s.get("fill_peaks", True))
    alpha = float(s.get("peak_alpha", DEFAULT_PEAK_ALPHA))

    annotate_peaks = bool(s.get("annotate_peaks", False))
    # ピークを図中で指し示すときは、既定で凡例からは外す（同じ情報の二重掲載を避ける）。
    peak_legend = bool(s.get("peak_legend", not annotate_peaks))

    main: list[dict[str, Any]] = []

    def add(kind: str, y: np.ndarray, *, label: str, color: str,
            zorder: int, width: float, dash: str = "-",
            fill_base: np.ndarray | None = None,
            in_legend: bool = True, apex: tuple[float, float] | None = None,
            apex_ceiling: float | None = None, annotate: bool = False,
            annotate_offset: Sequence[float] | None = None, column: str | None = None) -> None:
        main.append(dict(kind=kind, x=x, y=y, label=str(label), color=color,
                         dash=dash, width=width, zorder=zorder,
                         fill_base=fill_base, alpha=alpha, in_legend=in_legend,
                         apex=apex, apex_ceiling=apex_ceiling, annotate=annotate,
                         annotate_offset=annotate_offset, column=column))

    def shown(key: str) -> bool:
        return bool(s.get(f"show_{key}", True))

    if spectrum is not None and shown("spectrum"):
        add("spectrum", spectrum, label=labels["spectrum"],
            color=colors["spectrum"], zorder=5, width=COMPONENT_WIDTH["spectrum"])
    if composite is not None and shown("composite"):
        add("composite", composite, label=labels["composite"],
            color=colors["composite"], zorder=4,
            width=COMPONENT_WIDTH["composite"])
    if background is not None and shown("background"):
        add("background", background, label=labels["background"],
            color=colors["background"], zorder=3,
            width=COMPONENT_WIDTH["background"], dash=COMPONENT_DASH["background"])
    if peaks and shown("peaks"):
        # ピーク列はバックグラウンドを含む値。塗りつぶしの下端は背景（無ければ最小値）。
        if background is not None:
            base = background
        else:
            pool = [p["y"] for p in peaks] + [
                a for a in (spectrum, composite) if a is not None]
            base = np.full_like(x, float(np.nanmin(np.concatenate(pool))))
        stack = [a for a in (spectrum, composite) if a is not None] + [
            q["y"] for q in peaks]
        for i, p in enumerate(peaks):
            # 頂点は「背景を差し引いた成分」の最大位置（背景が傾いていてもずれない）。
            # フィット範囲が測定範囲より狭いCSVでは窓内が全NaNになり得るので守る。
            apex, ceiling = None, None
            if np.any(np.isfinite(p["y"])):
                top = int(np.nanargmax(np.where(np.isfinite(p["y"]),
                                                p["y"] - base, -np.inf)))
                apex = (float(x[top]), float(p["y"][top]))
                at_top = [a[top] for a in stack if np.isfinite(a[top])]
                ceiling = float(max(at_top)) if at_top else None
            add("peak", p["y"], apex=apex, apex_ceiling=ceiling,
                label=pick(s.get("peak_labels"), p["name"], i, p["name"]),
                color=pick(s.get("peak_colors"), p["name"], i,
                           PEAK_COLORS[i % len(PEAK_COLORS)]),
                zorder=2, width=PEAK_WIDTH,
                fill_base=base if fill_peaks else None,
                in_legend=peak_legend,
                annotate=annotate_peaks,
                annotate_offset=pick(s.get("peak_annotate_offsets"), p["name"], i, None),
                column=p["name"])

    # ---- 残差 ----
    res_trace, zero = None, None
    if residual is not None and mode != "none":
        res_trace = dict(kind="residual", x=x, y=residual,
                         label=str(labels["residual"]), color=colors["residual"],
                         dash=COMPONENT_DASH["residual"],
                         width=COMPONENT_WIDTH["residual"], zorder=3,
                         fill_base=None, alpha=alpha, in_legend=True,
                         apex=None, apex_ceiling=None, annotate=False,
                         annotate_offset=None, column=None)
        zero = 0.0
        if mode == "offset":
            # 同じ軸に描くので、データの下へ「残差の最大値ぶん」下げて重なりを防ぐ。
            pool = np.concatenate([t["y"] for t in main]) if main else residual
            lo_d, hi_d = float(np.nanmin(pool)), float(np.nanmax(pool))
            gap = float(s.get("residual_gap", DEFAULT_RESIDUAL_GAP)) * (
                (hi_d - lo_d) or 1.0)
            zero = lo_d - gap - float(np.nanmax(residual))
            res_trace["y"] = residual + zero

    return dict(main=main, residual=res_trace, residual_zero=zero, mode=mode)


def shift_prepared(prepared: Mapping[str, Any], offset: float) -> dict[str, Any]:
    """prepare_fit_traces の結果を y 方向に offset だけ平行移動する（重ね描き用）。

    塗りつぶしの下端・注釈の頂点・残差の0基準線も一緒に動かす。
    """
    def move(tr: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if tr is None:
            return None
        out = dict(tr)
        out["y"] = tr["y"] + offset
        if tr.get("fill_base") is not None:
            out["fill_base"] = tr["fill_base"] + offset
        if tr.get("apex") is not None:
            out["apex"] = (tr["apex"][0], tr["apex"][1] + offset)
        if tr.get("apex_ceiling") is not None:
            out["apex_ceiling"] = tr["apex_ceiling"] + offset
        return out

    zero = prepared.get("residual_zero")
    return dict(
        main=[move(t) for t in prepared["main"]],
        residual=move(prepared.get("residual")),
        residual_zero=None if zero is None else zero + offset,
        mode=prepared.get("mode"),
    )


def resolve_annotate_target(spec: Any, n: int) -> int | None:
    """annotate_on（"top"/"bottom"/"all"/番号）→ 注釈する段の添字（None=全部）。"""
    if spec is None or spec == "top":
        return n - 1          # 積み上げの一番上（既定。上に余白を作れる）
    if spec == "bottom":
        return 0
    if spec == "all":
        return None
    return int(spec) % n if n else 0


def stack_layers(prepared_list: Sequence[Mapping[str, Any]], *, offset_step: float,
                 annotate_on: Any = None) -> list[dict[str, Any]]:
    """段ごとの prepare 結果を i*offset_step だけ持ち上げる（1つの軸に積む用）。

    凡例は最初の段だけに付け、ピーク注釈は annotate_on で選んだ段だけに残す
    （同じ注釈の繰り返しを避ける）。戻り値は段ごとの {offset, prepared}。
    """
    target = resolve_annotate_target(annotate_on, len(prepared_list))
    layers = []
    for i, prepared in enumerate(prepared_list):
        moved = shift_prepared(prepared, i * offset_step)
        for tr in moved["main"]:
            if i > 0:
                tr["in_legend"] = False        # 成分の凡例は1組だけ
            if target is not None and i != target:
                tr["annotate"] = False
        if moved["residual"] is not None and i > 0:
            moved["residual"]["in_legend"] = False
        layers.append(dict(offset=i * offset_step, prepared=moved))
    return layers


# ============================================================ 図
def _axis_ref(n: int) -> tuple[str, str, str, str]:
    """n 番目（1始まり）の軸の組 (xaxis キー, yaxis キー, x 参照, y 参照)。"""
    k = "" if n == 1 else str(n)
    return f"xaxis{k}", f"yaxis{k}", f"x{k}", f"y{k}"


class _Legend:
    """同じ名前・色の系列は凡例に1回だけ載せる（パネルや段をまたいで重複させない）。"""

    def __init__(self) -> None:
        self.seen: set[tuple[str, str]] = set()

    def show(self, tr: Mapping[str, Any]) -> bool:
        if not tr.get("in_legend", True):
            return False
        key = (tr["label"], tr["color"])
        if key in self.seen:
            return False
        self.seen.add(key)
        return True


def _draw(st: dict, items: Sequence[Mapping[str, Any]], *, xaxis: str, yaxis: str,
          markers: bool, legend: _Legend) -> list[dict[str, Any]]:
    """トレース群を1つの軸に描く系列（Plotly の trace）のリストにする。

    返すリストは描く順（items の逆順。生スペクトルが一番手前、ピークの塗りつぶしが一番奥）。
    凡例は layout.legend.traceorder = "reversed" で items の順に並ぶ（_emit を参照）。
    凡例に載せるかどうかは items の順に決める（同じ名前・色は最初の1回だけ）。
    """
    scratch: dict[str, Any] = {"data": []}
    shows = [legend.show(tr) for tr in items]
    for tr, show in reversed(list(zip(items, shows))):
        width = st["line"] * tr["width"]
        dash = _DASH.get(tr["dash"], "solid")
        use_marker = markers and tr["kind"] == "spectrum"
        if tr.get("fill_base") is not None:
            # 塗りつぶしは「下端の見えない線 + tonexty」で表す
            base = add_line(scratch, tr["x"], tr["fill_base"], f"{tr['label']} (fill base)", st,
                            color=tr["color"], width=0, xaxis=xaxis, yaxis=yaxis,
                            showlegend=False)
            base["hoverinfo"] = "skip"
        add_line(scratch, tr["x"], tr["y"], tr["label"], st, color=tr["color"], width=width,
                 dash=dash, markers=use_marker, marker_size=st["marker"] * 0.55,
                 fill="tonexty" if tr.get("fill_base") is not None else None,
                 fillcolor=to_rgba(tr["color"], tr["alpha"]), xaxis=xaxis, yaxis=yaxis,
                 showlegend=show)
    return scratch["data"]


def _emit(fig, chunks: Sequence[list[dict[str, Any]]]) -> None:
    """パネル（段）ごとの系列を、凡例が「パネル順・成分順」に並ぶように図へ入れる。

    凡例は traceorder="reversed"（系列の逆順）で並ぶので、パネルも逆順に入れる。
    塗りつぶし（tonexty）の「下端の線 → ピーク」の並びはパネル内で保たれる。
    """
    fig["layout"]["legend"]["traceorder"] = "reversed"
    for chunk in reversed(chunks):
        fig["data"].extend(chunk)


def _data_bounds(items: Sequence[Mapping[str, Any]]) -> tuple[float, float] | None:
    vals = [np.asarray(t["y"], dtype=float) for t in items if t is not None and len(t["y"])]
    if not vals:
        return None
    allv = np.concatenate(vals)
    if not np.any(np.isfinite(allv)):
        return None
    return float(np.nanmin(allv)), float(np.nanmax(allv))


def _auto_range(lo: float, hi: float) -> tuple[float, float]:
    """自動の y 範囲（matplotlib の既定と同じく上下に 5% の余白）。"""
    pad = 0.05 * ((hi - lo) or 1.0)
    return lo - pad, hi + pad


def _annotate(fig, st: dict, traces: Sequence[Mapping[str, Any]], *, xref: str, yref: str,
              y_range: Sequence[float], px_height: float) -> None:
    """ピーク名を頂点に矢印つきで書き添える（凡例の代わりに図中で指し示す）。

    文字は「頂点の真上、ただしその x で一番上にある曲線より上」に置く。持ち上げる量は
    データ座標の差を px に換算して決める（y_range と、その軸の高さ px_height を使う）。
    peak_annotate_offsets（px 単位の [dx, dy]。dy は上向きが正。null の要素は自動）で調整できる。
    """
    span = float(y_range[1] - y_range[0]) or 1.0
    gap = st["annotation"] * 1.3
    for tr in traces:
        if not (tr.get("annotate") and tr.get("apex")):
            continue
        clearance = 0.0
        if tr.get("apex_ceiling") is not None:
            clearance = max(0.0, (tr["apex_ceiling"] - tr["apex"][1]) / span * px_height)
        offset = list(tr.get("annotate_offset") or (None, None))
        dx = 0.0 if offset[0] is None else float(offset[0])
        dy = clearance + gap if len(offset) < 2 or offset[1] is None else float(offset[1])
        add_annotation(fig, tr["apex"][0], tr["apex"][1], tr["label"], st, color=tr["color"],
                       arrow=True, ax=dx, ay=-dy, xref=xref, yref=yref,
                       xanchor="center" if abs(dx) < 1 else ("left" if dx > 0 else "right"),
                       yanchor="bottom" if dy >= 0 else "top")


def _complete(y_range: Sequence[float | None] | None,
              bounds: tuple[float, float] | None) -> tuple[float, float]:
    """注釈の位置計算に使う y 範囲（指定の無い側は自動範囲で埋める）。"""
    auto = _auto_range(*bounds) if bounds else (0.0, 1.0)
    if y_range is None:
        return auto
    lo, hi = y_range
    lo = auto[0] if lo is None else float(lo)
    hi = auto[1] if hi is None else float(hi)
    return min(lo, hi), max(lo, hi)


def _headroom_range(bounds: tuple[float, float], headroom: float) -> list[float]:
    """注釈が枠から飛び出さないよう、自動範囲の上端を headroom の割合だけ広げる。"""
    lo, hi = _auto_range(*bounds)
    return [lo, lo + (hi - lo) * (1 + headroom)]


def _plot_height(fig) -> float:
    lay = fig["layout"]
    return float(lay["height"] - lay["margin"]["t"] - lay["margin"]["b"])


def fit_panels_figure(
    panels: Sequence[Mapping[str, Any]],
    st: dict,
    *,
    fig_title: str | None = None,
    axis_ranges: Sequence[Mapping[str, Any]] | None = None,
    residual_mode: str = "offset",
    invert_x: bool = True,
    markers: bool = False,
    xlabel: str = DEFAULT_XLABEL,
    ylabel: str = DEFAULT_YLABEL,
    show_yticks: bool = False,
    legend_outside: bool = True,
    residual_ratio: float = DEFAULT_RESIDUAL_RATIO,
) -> dict[str, Any]:
    """フィット結果を「1ファイル = 1パネル」で縦に並べて描く。

    panels の各要素は {title, prepared, settings}（prepared は prepare_fit_traces の戻り、
    settings はそのパネルの設定: residual_zero_line / annotate_headroom / residual_ylabel）。
    residual_mode="panel" なら各パネルの上に残差の細いパネルを密着させて置く。
    """
    n = max(1, len(panels))
    with_residual = residual_mode == "panel"
    ratio = residual_ratio if with_residual else 0.0
    height = st["height"] * n * (1 + ratio)
    single = n == 1
    title = (panels[0]["title"] if panels else fig_title) if single else fig_title
    fig = new_figure(st, title=title, height=height,
                     legend="outside" if legend_outside else "inside")
    plot_h = _plot_height(fig)
    blocks = panel_domains(n, gap=min(0.3, PANEL_GAP_PX / plot_h)) if n > 1 else [[0.0, 1.0]]
    ranges = list(axis_ranges or [])
    while len(ranges) < n:
        ranges.append({})
    legend = _Legend()
    chunks: list[list[dict[str, Any]]] = []

    axis_no = 0
    for pi in range(n):
        panel = panels[pi] if pi < len(panels) else {"title": "", "prepared": None, "settings": {}}
        ps = panel.get("settings") or {}
        prepared = panel["prepared"] or dict(main=[], residual=None, residual_zero=None,
                                             mode=residual_mode)
        lo, hi = blocks[pi]
        if with_residual:
            split = lo + (hi - lo) * 1 / (1 + ratio)
            gap = RESIDUAL_GAP_PX / plot_h
            main_dom, res_dom = [lo, split - gap / 2], [split + gap / 2, hi]
        else:
            main_dom, res_dom = [lo, hi], None

        axis_no += 1
        xk, yk, xr, yr = _axis_ref(axis_no)
        res = prepared["residual"]
        on_main = res if (res is not None and prepared["mode"] == "offset") else None
        items = list(prepared["main"]) + ([on_main] if on_main else [])
        chunk = _draw(st, items, xaxis=xr, yaxis=yr, markers=markers, legend=legend)
        zero_line = bool(ps.get("residual_zero_line", True))
        if on_main is not None and zero_line:
            add_hline(fig, prepared["residual_zero"], color=on_main["color"], dash="dot",
                      width=st["line"] * 0.4, yref=yr)

        x_range = ranges[pi].get("x_range")
        y_range = ranges[pi].get("y_range")
        annotated = [t for t in prepared["main"] if t.get("annotate")]
        bounds = _data_bounds(items)
        if annotated and y_range is None and bounds is not None:
            y_range = _headroom_range(bounds, float(ps.get("annotate_headroom",
                                                           DEFAULT_ANNOTATE_HEADROOM)))
        set_axis(fig, xk, st, title=xlabel, range=x_range, reversed=invert_x,
                 anchor=yr if axis_no > 1 else None)
        set_axis(fig, yk, st, title=ylabel, range=y_range, show_ticklabels=show_yticks,
                 domain=main_dom if (n > 1 or with_residual) else None,
                 anchor=xr if axis_no > 1 else None)
        if annotated:
            _annotate(fig, st, annotated, xref=xr, yref=yr, y_range=_complete(y_range, bounds),
                      px_height=plot_h * (main_dom[1] - main_dom[0]))
        if not prepared["main"]:
            add_annotation(fig, 0.5, (main_dom[0] + main_dom[1]) / 2, "No valid data", st,
                           xref="paper", yref="paper", yanchor="middle")

        top = main_dom[1]
        if with_residual:
            axis_no += 1
            rxk, ryk, rxr, ryr = _axis_ref(axis_no)
            if res is not None:
                # 残差は凡例で本体の成分の後ろに来るよう、描く順では先頭に置く
                chunk = _draw(st, [res], xaxis=rxr, yaxis=ryr, markers=False, legend=legend) + chunk
                if zero_line:
                    add_hline(fig, 0.0, color=res["color"], dash="dot",
                              width=st["line"] * 0.4, yref=ryr)
            # 残差パネルの x は本体と同じ範囲・向きにし、目盛の数値と軸名は出さない
            set_axis(fig, rxk, st, range=x_range, reversed=invert_x, show_ticklabels=False,
                     anchor=ryr)
            set_axis(fig, ryk, st, title=ps.get("residual_ylabel"), show_ticklabels=show_yticks,
                     domain=res_dom, anchor=rxr)
            top = res_dom[1]
        if not single:
            add_annotation(fig, 0.5, top, panel["title"], st, xref="paper", yref="paper",
                           yanchor="bottom", yshift=6, size=st["axis_title"])
        chunks.append(chunk)
    _emit(fig, chunks)
    return fig


def fit_overlay_figure(
    layers: Sequence[Mapping[str, Any]],
    st: dict,
    *,
    fig_title: str | None = None,
    x_range: Sequence[float] | None = None,
    y_range: Sequence[float] | None = None,
    offset_step: float = DEFAULT_OFFSET_STEP,
    invert_x: bool = True,
    markers: bool = False,
    xlabel: str = DEFAULT_XLABEL,
    ylabel: str = DEFAULT_YLABEL,
    show_yticks: bool = False,
    legend_outside: bool = True,
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """複数ファイルのフィット結果を**1つの軸に**段で積み上げて描く（stack_layers の戻りを渡す）。

    layers の各要素は {offset, prepared, label}（label は段ラベル）。試料は色で区別できない
    （成分色を使うため）ので、凡例ではなく段のそばに段ラベルを直接書く。
    settings: baseline_guides / residual_zero_line / annotate_headroom /
    sample_label_pos / sample_label_ha / show_sample_labels。
    """
    s = dict(settings or {})
    n = max(1, len(layers))
    height = st["height"] * (4 + 2.2 * n) / 6.2     # kaiseki-tool の図の縦横比（10 × (4+2.2n) インチ）に合わせる
    fig = new_figure(st, title=fig_title, height=height,
                     legend="outside" if legend_outside else "inside")
    legend = _Legend()
    chunks: list[list[dict[str, Any]]] = []
    zero_line = bool(s.get("residual_zero_line", True))
    guides = bool(s.get("baseline_guides", True))
    all_items = []

    for layer in layers:
        prepared = layer["prepared"]
        res = prepared["residual"]
        on_main = res if (res is not None and prepared["mode"] == "offset") else None
        if guides:
            base_color = next((t["color"] for t in prepared["main"] if t["kind"] == "spectrum"),
                              COMPONENT_COLORS["spectrum"])
            add_hline(fig, layer["offset"], color=base_color, dash="dot",
                      width=st["line"] * 0.3, opacity=0.5)
        items = list(prepared["main"]) + ([on_main] if on_main else [])
        all_items += items
        chunks.append(_draw(st, items, xaxis="x", yaxis="y", markers=markers, legend=legend))
        if on_main is not None and zero_line:
            add_hline(fig, prepared["residual_zero"], color=on_main["color"], dash="dot",
                      width=st["line"] * 0.4)

    _emit(fig, chunks)
    annotated = [t for lay in layers for t in lay["prepared"]["main"] if t.get("annotate")]
    bounds = _data_bounds(all_items)
    if annotated and y_range is None and bounds is not None:
        headroom = float(s.get("annotate_headroom", DEFAULT_ANNOTATE_HEADROOM)) / n
        y_range = _headroom_range(bounds, headroom)
    set_axis(fig, "xaxis", st, title=xlabel, range=x_range, reversed=invert_x)
    set_axis(fig, "yaxis", st, title=ylabel, range=y_range, show_ticklabels=show_yticks)
    if annotated:
        _annotate(fig, st, annotated, xref="x", yref="y", y_range=_complete(y_range, bounds),
                  px_height=_plot_height(fig))

    # 段ラベル（x は軸の幅に対する割合、y はデータ座標）
    if bool(s.get("show_sample_labels", True)):
        lx, ly = s.get("sample_label_pos") or DEFAULT_SAMPLE_LABEL_POS
        ha = s.get("sample_label_ha") or ("right" if float(lx) > 0.5 else "left")
        for layer in layers:
            add_annotation(fig, float(lx), layer["offset"] + float(ly) * offset_step,
                           str(layer["label"]), st, xref="paper", yref="y",
                           xanchor=str(ha), yanchor="bottom")
    return fig
