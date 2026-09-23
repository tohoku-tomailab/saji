"""図の JSON（Plotly 形式）を matplotlib で SVG / PNG にする汎用の変換器。

手法の知識は持たない。docs/plotting.md の許可リストにある要素だけに対応する:
  - scatter（lines / markers、fill = tozeroy / tonexty）、bar（barmode stack / group、error_y、text）
  - 軸（タイトル、範囲・片側範囲、逆向き、対数、目盛の表示、domain による複数パネル、
    overlaying による第2y軸）
  - 凡例、注釈（矢印あり・なし）、shapes（line / rect）、図タイトル
それ以外の要素は無視する（見た目が完全一致する必要はなく、軸・データ・注釈の内容が
一致していればよい。HANDOFF §3.6）。

大きさの換算: 図の大きさは px / 96 インチ、文字・線は px × 0.75 pt
（どちらも 96 dpi の画面で Plotly と同じ見た目になる換算）。
"""

from __future__ import annotations

import io
import math
import re
from typing import Any

PX_PER_INCH = 96.0
PT_PER_PX = 0.75

FONT_CANDIDATES = ["Arial", "Liberation Sans", "Helvetica", "DejaVu Sans"]

_DASH = {"solid": "-", "dash": "--", "dot": ":", "dashdot": "-.", "longdash": "--"}
_SYMBOL = {"circle": "o", "square": "s", "diamond": "D", "triangle-up": "^",
           "triangle-down": "v", "cross": "P", "x": "X", "star": "*"}
_VA = {"top": "top", "middle": "center", "bottom": "bottom", "auto": "center"}
_HA = {"left": "left", "center": "center", "right": "right", "auto": "center"}

PLOTLY_DEFAULT_COLORWAY = ["#636efa", "#EF553B", "#00cc96", "#ab63fa", "#FFA15A",
                           "#19d3f3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52"]


def render(fig: dict[str, Any], fmt: str = "svg", *, dpi: int = 200) -> bytes:
    """図の JSON を fmt（"svg" / "png" / "pdf"）の bytes にする。"""
    import matplotlib
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    rc = {
        "font.family": _available_fonts(),
        "axes.unicode_minus": False,
        "svg.fonttype": "none",       # 文字を文字のまま残す（スライドで編集できる）
        "svg.hashsalt": "saji",       # SVG の id を決定的にする
        "mathtext.default": "regular",
    }
    with matplotlib.rc_context(rc):
        mfig = Figure()
        FigureCanvasAgg(mfig)
        _Renderer(fig, mfig).draw()
        buf = io.BytesIO()
        meta = {"Date": None} if fmt in ("svg", "pdf") else {}
        if fmt == "pdf":
            meta["CreationDate"] = None
            meta.pop("Date")
        mfig.savefig(buf, format=fmt, dpi=dpi, bbox_inches="tight",
                     facecolor=fig.get("layout", {}).get("paper_bgcolor", "#ffffff"),
                     metadata=meta)
    return buf.getvalue()


def _available_fonts() -> list[str]:
    from matplotlib import font_manager

    names = {f.name for f in font_manager.fontManager.ttflist}
    picked = [n for n in FONT_CANDIDATES if n in names]
    return picked or ["DejaVu Sans"]


# ============================================================ 文字・色
def html_to_mathtext(text: Any) -> str:
    """Plotly の簡易HTML（<sub> <sup> <br> <b> <i>）を matplotlib の文字列にする。"""
    s = "" if text is None else str(text)
    s = s.replace("$", r"\$")
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<sub>(.*?)</sub>", lambda m: "$_{" + m.group(1) + "}$", s, flags=re.I)
    s = re.sub(r"<sup>(.*?)</sup>", lambda m: "$^{" + m.group(1) + "}$", s, flags=re.I)
    return re.sub(r"</?[a-zA-Z][^>]*>", "", s)


def to_mpl_color(color: Any) -> Any:
    """#rrggbb / rgb() / rgba() / 色名 を matplotlib の色にする。"""
    if color is None:
        return None
    c = str(color).strip()
    m = re.fullmatch(r"rgba?\(([^)]*)\)", c)
    if m:
        parts = [float(v) for v in m.group(1).split(",")]
        r, g, b = (v / 255.0 for v in parts[:3])
        a = parts[3] if len(parts) > 3 else 1.0
        return (r, g, b, a)
    return c


def _pt(px: Any, default: float) -> float:
    return float(px if px is not None else default) * PT_PER_PX


def _floats(values: Any) -> list[float]:
    return [math.nan if v is None else float(v) for v in (values or [])]


def _axis_long(short: str, kind: str) -> str:
    """'x' → 'xaxis', 'x2' → 'xaxis2'。"""
    return kind + "axis" + short[1:]


# ============================================================ 本体
class _Renderer:
    def __init__(self, fig: dict[str, Any], mfig):
        self.fig = fig
        self.layout = fig.get("layout", {}) or {}
        self.mfig = mfig
        lay = self.layout
        self.W = float(lay.get("width") or 700)
        self.H = float(lay.get("height") or 450)
        mfig.set_size_inches(self.W / PX_PER_INCH, self.H / PX_PER_INCH)
        mg = {"l": 80, "r": 80, "t": 100, "b": 80, **(lay.get("margin") or {})}
        self.box = (mg["l"] / self.W, mg["b"] / self.H,
                    1 - (mg["l"] + mg["r"]) / self.W, 1 - (mg["t"] + mg["b"]) / self.H)
        font = lay.get("font") or {}
        self.base_font = font.get("size", 12)
        self.weight = font.get("weight", "normal")
        self.text_color = font.get("color", "#444444")
        self.axes: dict[tuple[str, str], Any] = {}
        self.handles: list[tuple[Any, str]] = []
        self.colorway = lay.get("colorway") or PLOTLY_DEFAULT_COLORWAY
        self._prev_y: dict[tuple[str, str], tuple[list[float], list[float]]] = {}
        self.categories: dict[str, list[Any]] = {}   # 分類軸の x → 分類名の並び

    # -------------------------------------------------- 座標変換
    def paper_transform(self):
        from matplotlib.transforms import Affine2D

        L, B, PW, PH = self.box
        return Affine2D().scale(PW, PH).translate(L, B) + self.mfig.transFigure

    def _font_kw(self, font: dict | None, default_size: float | None = None) -> dict[str, Any]:
        font = font or {}
        return {
            "fontsize": _pt(font.get("size"), default_size or self.base_font),
            "fontweight": font.get("weight", self.weight),
            "color": to_mpl_color(font.get("color", self.text_color)),
        }

    # -------------------------------------------------- 軸
    def _pairs(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for tr in self.fig.get("data", []):
            p = (tr.get("xaxis", "x"), tr.get("yaxis", "y"))
            if p not in pairs:
                pairs.append(p)
        return pairs or [("x", "y")]

    def build_axes(self) -> None:
        L, B, PW, PH = self.box
        pairs = self._pairs()
        base = [p for p in pairs if not self._yaxis(p[1]).get("overlaying")]
        twins = [p for p in pairs if self._yaxis(p[1]).get("overlaying")]
        for xk, yk in base:
            xd = self._xaxis(xk).get("domain") or [0, 1]
            yd = self._yaxis(yk).get("domain") or [0, 1]
            rect = [L + xd[0] * PW, B + yd[0] * PH, (xd[1] - xd[0]) * PW, (yd[1] - yd[0]) * PH]
            ax = self.mfig.add_axes(rect)
            ax.set_facecolor(to_mpl_color(self.layout.get("plot_bgcolor", "#ffffff")))
            self.axes[(xk, yk)] = ax
        for xk, yk in twins:
            under = self._yaxis(yk)["overlaying"]
            host = self.axes.get((xk, under)) or next(iter(self.axes.values()))
            self.axes[(xk, yk)] = host.twinx()

    def _xaxis(self, short: str) -> dict:
        return self.layout.get(_axis_long(short, "x")) or {}

    def _yaxis(self, short: str) -> dict:
        return self.layout.get(_axis_long(short, "y")) or {}

    def style_axes(self) -> None:
        for (xk, yk), ax in self.axes.items():
            yspec = self._yaxis(yk)
            twin = bool(yspec.get("overlaying"))
            if not twin:
                self._style_one(ax, self._xaxis(xk), "x", twin=False)
            self._style_one(ax, yspec, "y", twin=twin)

    def _style_one(self, ax, spec: dict, which: str, *, twin: bool) -> None:
        color = to_mpl_color(spec.get("linecolor", "#444444"))
        lw = _pt(spec.get("linewidth"), 1)
        title = spec.get("title") or {}
        text = title.get("text") if isinstance(title, dict) else title
        if text:
            kw = self._font_kw(title.get("font") if isinstance(title, dict) else None,
                               self.base_font)
            (ax.set_xlabel if which == "x" else ax.set_ylabel)(html_to_mathtext(text), **kw)
        if spec.get("type") == "log":
            (ax.set_xscale if which == "x" else ax.set_yscale)("log")

        mirror = bool(spec.get("mirror"))
        show = spec.get("showline", True)
        if which == "x":
            sides = ["bottom"] + (["top"] if mirror else [])
            if not twin:
                ax.spines["top"].set_visible(mirror and show)
        else:
            right_side = twin or spec.get("side") == "right"
            sides = (["right"] if right_side else ["left"]) + (["right"] if mirror and not right_side else [])
            if not twin:
                ax.spines["right"].set_visible(mirror and show)
        for side in sides:
            ax.spines[side].set_visible(bool(show))
            ax.spines[side].set_linewidth(lw)
            ax.spines[side].set_color(color)

        tickfont = spec.get("tickfont") or {}
        tick_kw = dict(
            axis=which, direction="in" if spec.get("ticks", "inside") == "inside" else "out",
            width=_pt(spec.get("tickwidth"), 1), length=_pt(spec.get("ticklen"), 5),
            color=color, labelsize=_pt(tickfont.get("size"), self.base_font),
            labelcolor=to_mpl_color(tickfont.get("color", self.text_color)),
        )
        show_labels = spec.get("showticklabels", True)
        if which == "x":
            tick_kw.update(bottom=True, top=mirror, labelbottom=show_labels, labeltop=False)
        elif twin or spec.get("side") == "right":
            tick_kw.update(right=True, left=False, labelright=show_labels, labelleft=False)
        else:
            tick_kw.update(left=True, right=mirror, labelleft=show_labels, labelright=False)
        ax.tick_params(**tick_kw)
        weight = tickfont.get("weight", self.weight)
        labels = ax.get_xticklabels() if which == "x" else ax.get_yticklabels()
        for lbl in labels:
            lbl.set_fontweight(weight)
        self._pending_weight = weight

    def apply_ranges(self) -> None:
        done: set[tuple[str, str]] = set()
        for (xk, yk), ax in self.axes.items():
            yspec = self._yaxis(yk)
            if not yspec.get("overlaying") and ("x", xk) not in done:
                self._range(ax, self._xaxis(xk), "x")
                done.add(("x", xk))
            self._range(ax, yspec, "y")

    def _range(self, ax, spec: dict, which: str) -> None:
        get = ax.get_xlim if which == "x" else ax.get_ylim
        set_ = ax.set_xlim if which == "x" else ax.set_ylim
        log = spec.get("type") == "log"
        rng = spec.get("range")
        auto = spec.get("autorange", True)
        conv = (lambda v: None if v is None else 10 ** v) if log else (lambda v: v)
        if rng and auto is False:
            set_(conv(rng[0]), conv(rng[1]))
            return
        reversed_ = isinstance(auto, str) and "reversed" in auto
        if rng and isinstance(auto, str) and auto.split()[0] in ("min", "max"):
            fixed = [v for v in rng if v is not None]
            lo_cur, hi_cur = sorted(get())
            if auto.startswith("max"):    # 下限を固定
                set_(conv(fixed[0]) if fixed else lo_cur, hi_cur)
            else:                         # 上限を固定
                set_(lo_cur, conv(fixed[0]) if fixed else hi_cur)
        if reversed_:
            lo, hi = get()
            set_(max(lo, hi), min(lo, hi))

    # -------------------------------------------------- 系列
    def _collect_categories(self) -> None:
        """文字列の x を持つ軸を分類軸とし、分類名を出現順に並べる（棒と線で共通の位置）。"""
        for tr in self.fig.get("data", []):
            xs = tr.get("x") or []
            if self._xaxis(tr.get("xaxis", "x")).get("type") == "category":
                xs = [str(v) for v in xs]
            if any(isinstance(v, str) for v in xs):
                cats = self.categories.setdefault(tr.get("xaxis", "x"), [])
                cats.extend(v for v in xs if v not in cats)

    def _xs(self, tr: dict) -> list[float]:
        cats = self.categories.get(tr.get("xaxis", "x"))
        if cats is None:
            return _floats(tr.get("x"))
        xs = tr.get("x") or []
        if self._xaxis(tr.get("xaxis", "x")).get("type") == "category":
            xs = [str(v) for v in xs]
        return [float(cats.index(v)) if v in cats else math.nan for v in xs]

    def draw_traces(self) -> None:
        self._collect_categories()
        bars: dict[tuple[str, str], list[tuple[int, dict]]] = {}
        for i, tr in enumerate(self.fig.get("data", [])):
            if tr.get("visible", True) in (False, "legendonly"):
                continue
            key = (tr.get("xaxis", "x"), tr.get("yaxis", "y"))
            color = self.colorway[i % len(self.colorway)]
            if tr.get("type", "scatter") == "bar":
                bars.setdefault(key, []).append((i, tr))
            elif tr.get("type", "scatter") == "scatter":
                self._scatter(self.axes[key], key, tr, color)
        for key, items in bars.items():
            self._bars(self.axes[key], items)
        for (xk, yk), ax in self.axes.items():
            cats = self.categories.get(xk)
            if cats and not self._yaxis(yk).get("overlaying"):
                ax.set_xticks(range(len(cats)))
                ax.set_xticklabels([html_to_mathtext(c) for c in cats])
                ax.set_xlim(-0.6, len(cats) - 0.4)

    def _label(self, tr: dict) -> str:
        return html_to_mathtext(tr.get("name", "")) if tr.get("showlegend", True) else "_nolegend_"

    def _scatter(self, ax, key, tr: dict, default_color: str) -> None:
        x, y = self._xs(tr), _floats(tr.get("y"))
        mode = tr.get("mode", "lines")
        line = tr.get("line") or {}
        marker = tr.get("marker") or {}
        color = to_mpl_color(line.get("color") or marker.get("color") or default_color)
        label = self._label(tr)
        handle = None
        if "lines" in mode or "markers" in mode:
            kw: dict[str, Any] = {"color": color, "label": label}
            if "lines" in mode:
                kw.update(linestyle=_DASH.get(line.get("dash", "solid"), "-"),
                          linewidth=_pt(line.get("width"), 2))
            else:
                kw["linestyle"] = "none"
            if "markers" in mode:
                edge = (marker.get("line") or {})
                kw.update(marker=_SYMBOL.get(marker.get("symbol", "circle"), "o"),
                          markersize=_pt(marker.get("size"), 6),
                          markerfacecolor=to_mpl_color(marker.get("color") or color),
                          markeredgecolor=to_mpl_color(edge.get("color") or marker.get("color") or color),
                          markeredgewidth=_pt(edge.get("width"), 0))
            (handle,) = ax.plot(x, y, **kw)
        err = tr.get("error_y") or {}
        if err.get("visible", True) and err.get("array"):
            ax.errorbar(x, y, yerr=_floats(err["array"]), fmt="none",
                        ecolor=to_mpl_color(err.get("color") or color),
                        elinewidth=_pt(err.get("thickness"), 2), capsize=_pt(err.get("width"), 4))
        fill = tr.get("fill")
        if fill in ("tozeroy", "tonexty"):
            fc = to_mpl_color(tr.get("fillcolor")) or _with_alpha(color, 0.5)
            base = [0.0] * len(y)
            if fill == "tonexty" and key in self._prev_y:
                px, py = self._prev_y[key]
                base = _interp(x, px, py)
            poly = ax.fill_between(x, base, y, color=fc, linewidth=0,
                                   label="_nolegend_" if handle is not None else label)
            handle = handle or poly
        self._prev_y[key] = (x, y)
        if handle is not None and label != "_nolegend_":
            self.handles.append((handle, label))

    def _bars(self, ax, items: list[tuple[int, dict]]) -> None:
        import numpy as np

        mode = self.layout.get("barmode", "group")
        n = len(items)
        bottoms: dict[float, float] = {}
        for j, (i, tr) in enumerate(items):
            xpos = np.array(self._xs(tr))
            xs = list(xpos)
            ys = _floats(tr.get("y"))
            width = float(tr.get("width") or 0.8)
            if mode == "group" and n > 1:
                w = width / n
                xpos = xpos - width / 2 + w * (j + 0.5)
                width = w
            bottom = [bottoms.get(c, 0.0) if mode == "stack" else 0.0 for c in xs]
            marker = tr.get("marker") or {}
            edge = marker.get("line") or {}
            err = tr.get("error_y") or {}
            yerr = _floats(err.get("array")) if err.get("visible", True) and err.get("array") else None
            color = to_mpl_color(marker.get("color") or self.colorway[i % len(self.colorway)])
            cont = ax.bar(xpos, ys, width, bottom=bottom, color=color,
                          edgecolor=to_mpl_color(edge.get("color", "#000000")),
                          linewidth=_pt(edge.get("width"), 0), label=self._label(tr))
            if yerr is not None:
                tops = [b + (0 if math.isnan(v) else v) for b, v in zip(bottom, ys)]
                ax.errorbar(xpos, tops, yerr=yerr, fmt="none",
                            ecolor=to_mpl_color(err.get("color", "#000000")),
                            elinewidth=_pt(err.get("thickness"), 2), capsize=_pt(err.get("width"), 4))
            texts = tr.get("text")
            if texts:
                tf = tr.get("textfont") or {}
                for xp, b, v, t in zip(xpos, bottom, ys, texts):
                    if t and not math.isnan(v):
                        ax.text(xp, b + v / 2, html_to_mathtext(t), ha="center", va="center",
                                **self._font_kw(tf, self.base_font))
            if mode == "stack":
                for c, v in zip(xs, ys):
                    bottoms[c] = bottoms.get(c, 0.0) + (0.0 if math.isnan(v) else v)
            if tr.get("showlegend", True):
                self.handles.append((cont, self._label(tr)))

    # -------------------------------------------------- 図形・注釈
    def _axes_for(self, xref: str, yref: str):
        """xref / yref（"x2" / "y domain" / "paper"）に対応する Axes と変換を返す。"""
        from matplotlib.transforms import blended_transform_factory

        xs, ys = xref.split()[0], yref.split()[0]
        ax = None
        for (xk, yk), a in self.axes.items():
            if (xs == "paper" or xk == xs) and (ys == "paper" or yk == ys):
                ax = a
                break
        ax = ax or next(iter(self.axes.values()))
        paper = self.paper_transform()

        def tf(ref: str, which: str):
            if ref == "paper":
                return paper
            if ref.endswith("domain"):
                return ax.transAxes
            return ax.transData

        xt, yt = tf(xref, "x"), tf(yref, "y")
        if xt is yt:
            return ax, xt
        return ax, blended_transform_factory(xt, yt)

    def draw_shapes(self) -> None:
        from matplotlib.patches import Rectangle

        for sh in self.layout.get("shapes") or []:
            xref, yref = sh.get("xref", "x"), sh.get("yref", "y")
            line = sh.get("line") or {}
            alpha = float(sh.get("opacity", 1.0))
            targets = self._shape_targets(xref, yref)
            for ax, tf in targets:
                if sh.get("type") == "rect":
                    x0, x1 = float(sh["x0"]), float(sh["x1"])
                    y0, y1 = float(sh["y0"]), float(sh["y1"])
                    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, transform=tf,
                                           facecolor=to_mpl_color(sh.get("fillcolor", "#888888")),
                                           alpha=alpha, linewidth=0, zorder=0, clip_on=False))
                elif sh.get("type") == "line":
                    ax.plot([float(sh["x0"]), float(sh["x1"])], [float(sh["y0"]), float(sh["y1"])],
                            transform=tf, color=to_mpl_color(line.get("color", "#444444")),
                            linewidth=_pt(line.get("width"), 2), alpha=alpha,
                            linestyle=_DASH.get(line.get("dash", "solid"), "-"),
                            zorder=0.5, scalex=False, scaley=False)

    def _shape_targets(self, xref: str, yref: str):
        """paper を含む図形は、同じ x（または y）を持つ全パネルに描く。"""
        if yref == "paper" and not xref.startswith("paper"):
            out = []
            for (xk, yk), ax in self.axes.items():
                if xk == xref.split()[0] and not self._yaxis(yk).get("overlaying"):
                    from matplotlib.transforms import blended_transform_factory
                    out.append((ax, blended_transform_factory(ax.transData, ax.transAxes)))
            return out or [self._axes_for(xref, yref)]
        if xref == "paper" and not yref.startswith("paper"):
            out = []
            for (xk, yk), ax in self.axes.items():
                if yk == yref.split()[0]:
                    from matplotlib.transforms import blended_transform_factory
                    out.append((ax, blended_transform_factory(ax.transAxes, ax.transData)))
            return out or [self._axes_for(xref, yref)]
        return [self._axes_for(xref, yref)]

    def draw_annotations(self) -> None:
        for ann in self.layout.get("annotations") or []:
            ax, tf = self._axes_for(ann.get("xref", "x"), ann.get("yref", "y"))
            text = html_to_mathtext(ann.get("text", ""))
            kw = self._font_kw(ann.get("font"), self.base_font)
            xy = (float(ann["x"]), float(ann["y"]))
            if ann.get("showarrow", True):
                dx = float(ann.get("ax", -10)) * PT_PER_PX
                dy = -float(ann.get("ay", -30)) * PT_PER_PX
                ax.annotate(text, xy=xy, xycoords=tf, xytext=(dx, dy), textcoords="offset points",
                            ha="center", va="center", annotation_clip=False,
                            arrowprops={"arrowstyle": "-", "color": to_mpl_color(
                                ann.get("arrowcolor", kw["color"])),
                                "lw": _pt(ann.get("arrowwidth"), 1), "shrinkA": 2, "shrinkB": 2},
                            **kw)
            else:
                dx = float(ann.get("xshift", 0)) * PT_PER_PX
                dy = float(ann.get("yshift", 0)) * PT_PER_PX
                ax.annotate(text, xy=xy, xycoords=tf, xytext=(dx, dy), textcoords="offset points",
                            ha=_HA.get(ann.get("xanchor", "center"), "center"),
                            va=_VA.get(ann.get("yanchor", "middle"), "center"),
                            annotation_clip=False, **kw)

    # -------------------------------------------------- 凡例・タイトル
    def draw_legend(self) -> None:
        if not self.layout.get("showlegend", True) or not self.handles:
            return
        leg = self.layout.get("legend") or {}
        handles = list(self.handles)
        order = leg.get("traceorder")
        stacked = self.layout.get("barmode") == "stack" and any(
            t.get("type") == "bar" for t in self.fig.get("data", []))
        if order == "reversed" or (order is None and stacked):
            handles.reverse()
        x, y = float(leg.get("x", 1.02)), float(leg.get("y", 1.0))
        xa = leg.get("xanchor", "left")
        ya = leg.get("yanchor", "auto")
        if ya == "auto":
            ya = "top" if y >= 2 / 3 else ("bottom" if y <= 1 / 3 else "middle")
        vert = {"top": "upper", "middle": "center", "bottom": "lower"}[ya]
        loc = f"{vert} {xa}" if not (vert == "center" and xa == "center") else "center"
        font = leg.get("font") or {}
        first = next(iter(self.axes.values()))
        first.legend([h for h, _ in handles], [lbl for _, lbl in handles], loc=loc,
                     bbox_to_anchor=(x, y), bbox_transform=self.paper_transform(),
                     frameon=False, borderaxespad=0,
                     prop={"size": _pt(font.get("size"), self.base_font),
                           "weight": font.get("weight", self.weight)},
                     labelcolor=to_mpl_color(font.get("color", self.text_color)))

    def draw_title(self) -> None:
        title = self.layout.get("title")
        if not title:
            return
        text = title.get("text") if isinstance(title, dict) else title
        if not text:
            return
        L, B, PW, PH = self.box
        x = float(title.get("x", 0.5)) if isinstance(title, dict) else 0.5
        y = B + PH + 12 / self.H
        sub = title.get("subtitle") if isinstance(title, dict) else None
        if isinstance(sub, dict) and sub.get("text"):
            t = self.mfig.text(L + PW * x, y, html_to_mathtext(sub["text"]), ha="center", va="bottom",
                               **self._font_kw(sub.get("font"), self.base_font))
            y += (t.get_fontsize() / 72 * 1.5) / self.mfig.get_size_inches()[1]
        self.mfig.text(L + PW * x, y, html_to_mathtext(text), ha="center", va="bottom",
                       **self._font_kw(title.get("font") if isinstance(title, dict) else None,
                                       self.base_font))

    def draw(self) -> None:
        self.build_axes()
        self.draw_traces()
        self.style_axes()
        self.apply_ranges()
        self.draw_shapes()
        self.draw_annotations()
        self.draw_legend()
        self.draw_title()
        for ax in self.axes.values():
            for lbl in ax.get_xticklabels() + ax.get_yticklabels():
                lbl.set_fontweight(self.weight)


def _with_alpha(color: Any, alpha: float):
    from matplotlib.colors import to_rgba

    return to_rgba(color, alpha)


def _interp(x: list[float], px: list[float], py: list[float]) -> list[float]:
    """直前の系列 (px, py) を x の位置の値にそろえる（tonexty 用）。"""
    import numpy as np

    if len(px) == len(x) and all(a == b for a, b in zip(px, x)):
        return list(py)
    order = np.argsort(px)
    return list(np.interp(x, np.asarray(px)[order], np.asarray(py)[order]))
