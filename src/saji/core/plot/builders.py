"""Plotly の図の形式（JSON の dict）を組み立てる補助関数。

``plotly`` パッケージは使わない（Web で読み込むパッケージを減らすため）。
使ってよい要素は docs/plotting.md の許可リストに限る。ここにある関数は許可した
要素だけを作るので、原則としてこれらを通して図を組み立てること。

座標の値は numpy 配列でもよい（to_jsonable で list にし、NaN は null にする）。

使い方の例::

    st = get_style(params["style"])
    fig = new_figure(st, title="sample")
    set_axis(fig, "xaxis", st, title="2θ / deg")
    set_axis(fig, "yaxis", st, title="Intensity / a.u.")
    add_line(fig, x, y, "sample", st, color="#1e33ff")
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from .style import AXIS_COLOR, BACKGROUND, FONT_FAMILY, FONT_WEIGHT, SERIES_COLORS, TEXT_COLOR, font

Fig = dict[str, Any]

DASHES = ("solid", "dash", "dot", "dashdot")
SYMBOLS = ("circle", "square", "diamond", "triangle-up", "triangle-down", "cross", "x", "star")


# ============================================================ 図と軸
def new_figure(st: dict, *, title: str | None = None, subtitle: str | None = None,
               width: float | None = None, height: float | None = None,
               legend: str = "outside") -> Fig:
    """白背景・Arial 太字・枠線ありの空の図を作る。

    subtitle はタイトルの下に小さく出す（処理条件など）。
    legend: "outside"（軸の右外。既定）/ "inside"（軸内の右上）/ "none"（出さない）。
    """
    layout: dict[str, Any] = {
        "width": int(width or st["width"]),
        "height": int(height or st["height"]),
        "plot_bgcolor": BACKGROUND,
        "paper_bgcolor": BACKGROUND,
        "font": font(st["font"]),
        "colorway": list(SERIES_COLORS),
        "margin": {"l": 90, "r": 30, "t": (100 if subtitle else 70) if title else 30, "b": 80},
        "showlegend": legend != "none",
        "legend": _legend(st, legend),
        "shapes": [],
        "annotations": [],
    }
    if title:
        layout["title"] = {"text": title, "font": font(st["title"]), "x": 0.5, "xanchor": "center"}
        if subtitle:
            layout["title"]["subtitle"] = {"text": subtitle, "font": font(st["tick"] * 0.8)}
    return {"data": [], "layout": layout}


def _legend(st: dict, where: str) -> dict[str, Any]:
    leg: dict[str, Any] = {"font": font(st["legend"]), "bgcolor": "rgba(255,255,255,0)"}
    if where == "inside":
        leg.update(x=0.98, y=0.98, xanchor="right", yanchor="top")
    else:
        leg.update(x=1.02, y=0.5, xanchor="left", yanchor="middle")
    return leg


def set_axis(fig: Fig, key: str, st: dict, *, title: str | None = None,
             range: Sequence[float | None] | None = None, reversed: bool = False,
             log: bool = False, show_ticklabels: bool = True,
             domain: Sequence[float] | None = None, anchor: str | None = None,
             overlaying: str | None = None, side: str | None = None,
             color: str | None = None, mirror: bool = True) -> dict[str, Any]:
    """軸（xaxis / yaxis / xaxis2 …）を設定して返す。

    range は [下限, 上限]（片側 None なら自動。順不同で与えてよい）。reversed=True で
    大→小（XPS の結合エネルギーなど）。overlaying="y" + side="right" で第2y軸。
    """
    c = color or AXIS_COLOR
    axis: dict[str, Any] = {
        "showgrid": False, "zeroline": False,
        "showline": True, "linecolor": c, "linewidth": st["axis_line"],
        "mirror": mirror and overlaying is None,
        "ticks": "inside", "tickwidth": st["axis_line"], "tickcolor": c,
        "ticklen": st["tick_len"], "tickfont": font(st["tick"], c),
        "showticklabels": show_ticklabels, "automargin": True,
    }
    if title:
        axis["title"] = {"text": title, "font": font(st["axis_title"], c)}
    if log:
        axis["type"] = "log"
    rng = _clean_range(range)
    if rng is not None:
        lo, hi = rng
        if lo is not None and hi is not None:
            lo, hi = min(lo, hi), max(lo, hi)
            if log:
                lo, hi = math.log10(lo), math.log10(hi)
            axis["range"] = [hi, lo] if reversed else [lo, hi]
            axis["autorange"] = False
        else:
            # 片側だけ指定: 指定の無い側だけ自動にする（Plotly の "min" / "max" autorange）
            auto_side = "max" if lo is not None else "min"
            axis["range"] = [hi, lo] if reversed else [lo, hi]
            axis["autorange"] = f"{auto_side} reversed" if reversed else auto_side
    elif reversed:
        axis["autorange"] = "reversed"
    if domain is not None:
        axis["domain"] = [float(domain[0]), float(domain[1])]
    if anchor:
        axis["anchor"] = anchor
    if overlaying:
        # 第2軸の目盛は自分の範囲で決める（Plotly の既定 "sync" だと半端な値になる）
        axis["tickmode"] = "auto"
        axis["overlaying"] = overlaying
        axis["side"] = side or "right"
    elif side:
        axis["side"] = side
    fig["layout"][key] = axis
    _fit_twin_axes(fig)
    return axis


def _fit_twin_axes(fig: Fig) -> None:
    """第2y軸があるとき、元の軸の右側の枠（mirror）を消し、軸外の凡例を右へ逃がす。"""
    layout = fig["layout"]
    for k, ax in list(layout.items()):
        if not (k.startswith("yaxis") and isinstance(ax, dict) and ax.get("overlaying")):
            continue
        base = layout.get("yaxis" + ax["overlaying"][1:])
        if base is not None:
            base["mirror"] = False
        leg = layout.get("legend") or {}
        if ax.get("side") == "right" and float(leg.get("x", 0)) >= 1:
            leg["x"] = max(float(leg["x"]), 1.14)


def _clean_range(r: Sequence[float | None] | None) -> list[float | None] | None:
    if r is None:
        return None
    lo, hi = r
    if lo is None and hi is None:
        return None
    return [None if lo is None else float(lo), None if hi is None else float(hi)]


def panel_domains(n: int, *, gap: float = 0.08, ratios: Sequence[float] | None = None) -> list[list[float]]:
    """縦に n 枚並べるパネルの y の domain を、上から順に返す。

    ratios で各パネルの高さの比を指定できる（既定は均等）。
    """
    ratios = list(ratios or [1.0] * n)
    usable = 1.0 - gap * (n - 1)
    total = sum(ratios)
    out, top = [], 1.0
    for r in ratios:
        h = usable * r / total
        out.append([max(0.0, top - h), top])
        top = top - h - gap
    return out


# ============================================================ 系列
def add_line(fig: Fig, x: Sequence, y: Sequence, name: str, st: dict, *,
             color: str | None = None, width: float | None = None, dash: str = "solid",
             markers: bool = False, lines: bool = True, marker_symbol: str = "circle",
             marker_size: float | None = None, fill: str | None = None,
             fillcolor: str | None = None, xaxis: str = "x", yaxis: str = "y",
             showlegend: bool = True, legendgroup: str | None = None,
             hover_digits: int = 4) -> dict[str, Any]:
    """線・散布図（scatter）を追加する。

    fill: None / "tozeroy"（y=0 まで塗る）/ "tonexty"（直前の系列まで塗る）。
    """
    if dash not in DASHES:
        raise ValueError(f"未対応の線種: {dash}（{DASHES}）")
    if marker_symbol not in SYMBOLS:
        raise ValueError(f"未対応のマーカー: {marker_symbol}（{SYMBOLS}）")
    if fill not in (None, "tozeroy", "tonexty"):
        raise ValueError(f"未対応の塗りつぶし: {fill}")
    mode = "+".join(m for m, on in (("lines", lines), ("markers", markers)) if on) or "lines"
    tr: dict[str, Any] = {
        "type": "scatter", "mode": mode, "name": str(name),
        "x": to_jsonable(x), "y": to_jsonable(y),
        "xaxis": xaxis, "yaxis": yaxis, "showlegend": showlegend,
        "hovertemplate": f"x=%{{x:.{hover_digits}f}}<br>y=%{{y:.{hover_digits}g}}<extra>%{{fullData.name}}</extra>",
    }
    if lines:
        tr["line"] = {"width": width if width is not None else st["line"], "dash": dash}
        if color:
            tr["line"]["color"] = color
    if markers:
        tr["marker"] = {"symbol": marker_symbol, "size": marker_size or st["marker"]}
        if color:
            tr["marker"]["color"] = color
            tr["marker"]["line"] = {"color": "#000000", "width": 0.5}
    if fill:
        tr["fill"] = fill
        if fillcolor:
            tr["fillcolor"] = fillcolor
    if legendgroup:
        tr["legendgroup"] = legendgroup
    fig["data"].append(tr)
    return tr


def add_bar(fig: Fig, x: Sequence, y: Sequence, name: str, *, color: str | None = None,
            error: Sequence[float] | None = None, xaxis: str = "x", yaxis: str = "y",
            width: float | None = None, showlegend: bool = True, error_width: float = 2.0,
            text: Sequence[str] | None = None, text_size: float | None = None) -> dict[str, Any]:
    """棒グラフの系列を追加する。積み上げは layout の barmode="stack" で指定する。

    text を渡すと棒の中央に数値ラベルを書く（空文字の要素は書かない）。
    """
    tr: dict[str, Any] = {
        "type": "bar", "name": str(name), "x": to_jsonable(x), "y": to_jsonable(y),
        "xaxis": xaxis, "yaxis": yaxis, "showlegend": showlegend,
        "marker": {"line": {"color": "#000000", "width": 1}},
    }
    if color:
        tr["marker"]["color"] = color
    if width is not None:
        tr["width"] = width
    if error is not None:
        tr["error_y"] = {"type": "data", "array": to_jsonable(error), "visible": True,
                         "color": "#000000", "thickness": error_width, "width": 5}
    if text is not None:
        tr["text"] = [str(t) for t in text]
        tr["textposition"] = "inside"
        tr["insidetextanchor"] = "middle"
        tr["textfont"] = {"family": FONT_FAMILY, "weight": FONT_WEIGHT, "color": TEXT_COLOR}
        if text_size:
            tr["textfont"]["size"] = text_size
    fig["data"].append(tr)
    return tr


def offset_values(n: int, step: float, *, bottom_up: bool = False) -> list[float]:
    """n 本の系列をずらして重ねるときの各系列のオフセット。

    既定（top-down）はリスト先頭を最上段にする。bottom_up=True で先頭を最下段に。
    """
    return [(i if bottom_up else n - 1 - i) * step for i in range(n)]


# ============================================================ 縦線・網掛け
def add_vline(fig: Fig, x: float, *, color: str = "#888888", width: float = 1.5,
              dash: str = "dot", opacity: float = 1.0, xref: str = "x",
              yref: str = "paper", y0: float = 0.0, y1: float = 1.0) -> None:
    """縦線を追加する（既定は軸の上端から下端まで）。

    パネルが複数あるときは yref="y2 domain" のように、そのパネルの軸を指す。
    """
    fig["layout"]["shapes"].append({
        "type": "line", "xref": xref, "yref": yref, "x0": float(x), "x1": float(x),
        "y0": y0, "y1": y1, "opacity": opacity,
        "line": {"color": color, "width": width, "dash": dash},
    })


def add_hline(fig: Fig, y: float, *, color: str = "#888888", width: float = 1.0,
              dash: str = "dot", opacity: float = 1.0, xref: str = "paper", yref: str = "y") -> None:
    """横線を追加する（既定は軸の左端から右端まで）。"""
    fig["layout"]["shapes"].append({
        "type": "line", "xref": xref, "yref": yref, "x0": 0, "x1": 1,
        "y0": float(y), "y1": float(y), "opacity": opacity,
        "line": {"color": color, "width": width, "dash": dash},
    })


def add_vrect(fig: Fig, x0: float, x1: float, *, color: str = "#888888", opacity: float = 0.2,
              xref: str = "x", yref: str = "paper") -> None:
    """x の範囲を網掛けする（背景の区間などを示す）。"""
    fig["layout"]["shapes"].append({
        "type": "rect", "xref": xref, "yref": yref, "x0": float(x0), "x1": float(x1),
        "y0": 0, "y1": 1, "fillcolor": color, "opacity": opacity, "line": {"width": 0},
        "layer": "below",
    })


# ============================================================ 注釈
def add_annotation(fig: Fig, x: float, y: float, text: str, st: dict, *,
                   color: str | None = None, size: float | None = None,
                   arrow: bool = False, ax: float = 0, ay: float = -30,
                   xref: str = "x", yref: str = "y", xanchor: str = "center",
                   yanchor: str = "bottom", yshift: float = 0, xshift: float = 0) -> None:
    """文字の注釈を追加する。

    arrow=True なら (x, y) を矢印で指し、文字は (ax, ay) px だけずれた位置に置く
    （ay は下向きが正なので、上に置くなら負）。arrow=False なら (x, y) に文字を置き、
    xanchor / yanchor と xshift / yshift（px、上向きが正）で位置を調整する。
    xref / yref に "paper" を渡すと図の描画領域に対する割合（0〜1）になる。
    """
    c = color or TEXT_COLOR
    ann: dict[str, Any] = {
        "x": float(x), "y": float(y), "xref": xref, "yref": yref, "text": str(text),
        "font": font(size or st["annotation"], c), "showarrow": bool(arrow),
        "xanchor": xanchor, "yanchor": yanchor,
    }
    if arrow:
        ann.update(ax=float(ax), ay=float(ay), arrowcolor=c, arrowwidth=1.5,
                   arrowhead=0, standoff=2)
    else:
        ann.update(xshift=float(xshift), yshift=float(yshift))
    fig["layout"]["annotations"].append(ann)


# ============================================================ JSON 化
def to_jsonable(values: Any) -> Any:
    """numpy 配列などを JSON にできる list にする（NaN / inf は None）。"""
    if values is None:
        return None
    if hasattr(values, "tolist"):
        values = values.tolist()
    if isinstance(values, (list, tuple)):
        return [to_jsonable(v) for v in values]
    if isinstance(values, float) and not math.isfinite(values):
        return None
    if hasattr(values, "item"):   # numpy のスカラー
        return to_jsonable(values.item())
    return values
