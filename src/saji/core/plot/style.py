"""図の共通スタイル（Plotly の見た目が主。matplotlib 変換器もこれに揃える）。

主な使い方は「ブラウザの Plotly で描いて少しいじり、スクショしてスライドに貼る」。
そのため Plotly 側の見た目をそのまま発表に使える大きさ・太さにしてある。
サイズは Plotly の px 単位（matplotlib 変換器が pt に換算する）。

プリセットは paper / slide（既定）/ poster。フォントは Arial に統一し、太字にする。
"""

from __future__ import annotations

from typing import Any

from ..tool import Param

FONT_FAMILY = "Arial"
FONT_WEIGHT = "bold"
TEXT_COLOR = "#222222"
AXIS_COLOR = "#222222"
BACKGROUND = "#ffffff"

STYLES: dict[str, dict[str, float]] = {
    "paper": dict(font=14, axis_title=16, tick=14, legend=13, title=16, annotation=13,
                  line=2.0, line_thin=1.4, marker=7, axis_line=1.6, tick_len=6,
                  width=900, height=560),
    "slide": dict(font=18, axis_title=22, tick=18, legend=17, title=20, annotation=16,
                  line=2.6, line_thin=1.8, marker=9, axis_line=2.0, tick_len=8,
                  width=1000, height=620),
    "poster": dict(font=22, axis_title=26, tick=22, legend=20, title=24, annotation=19,
                   line=3.2, line_thin=2.2, marker=11, axis_line=2.4, tick_len=10,
                   width=1100, height=680),
}
DEFAULT_STYLE = "slide"

# 系列色（黒→赤→緑→青→水色→紫…。kaiseki-tool の探索用と同じ並び）。
SERIES_COLORS = [
    "#111111", "#ff1e1e", "#00a82a", "#1e33ff", "#00b8c8", "#9b34eb",
    "#ff7eb6", "#e0a000", "#7a6a00", "#8b4513",
]

# 図を出すツールが共通で持つパラメータ（ツール定義の params に入れて使う）。
STYLE_PARAM = Param(
    "style", choices=tuple(STYLES), default=DEFAULT_STYLE, group="図",
    help="文字・線の大きさのプリセット（paper=論文 / slide=スライド / poster=ポスター）",
)


def get_style(name: str | None = None) -> dict[str, float]:
    """プリセット名 → スタイル dict（コピー）。"""
    key = name or DEFAULT_STYLE
    if key not in STYLES:
        raise ValueError(f"未知のスタイル: {name}（候補: {', '.join(STYLES)}）")
    return dict(STYLES[key])


def series_color(index: int, color: str | None = None) -> str:
    """系列番号 → 既定色（明示指定があればそれ）。"""
    return color or SERIES_COLORS[index % len(SERIES_COLORS)]


def to_rgba(color: str, alpha: float) -> str:
    """#rrggbb / rgb(...) を rgba 文字列にする（塗りつぶし用）。"""
    c = str(color).strip()
    if c.startswith("#") and len(c) == 7:
        r, g, b = (int(c[i:i + 2], 16) for i in (1, 3, 5))
        return f"rgba({r},{g},{b},{alpha})"
    if c.startswith("rgb(") and c.endswith(")"):
        return f"rgba({c[4:-1]},{alpha})"
    return c


def font(size: float, color: str = TEXT_COLOR) -> dict[str, Any]:
    return {"family": FONT_FAMILY, "size": size, "color": color, "weight": FONT_WEIGHT}


# matplotlib の色名（tab:red など）→ #rrggbb。既存の設定ファイル（ピーク表など）との互換用。
TAB_COLORS = {
    "tab:blue": "#1f77b4", "tab:orange": "#ff7f0e", "tab:green": "#2ca02c",
    "tab:red": "#d62728", "tab:purple": "#9467bd", "tab:brown": "#8c564b",
    "tab:pink": "#e377c2", "tab:gray": "#7f7f7f", "tab:grey": "#7f7f7f",
    "tab:olive": "#bcbd22", "tab:cyan": "#17becf",
}
_TAB10 = [TAB_COLORS[f"tab:{n}"] for n in
          ("blue", "orange", "green", "red", "purple", "brown", "pink", "gray", "olive", "cyan")]

# matplotlib のマーカー記号 → Plotly のマーカー名。
MPL_MARKERS = {
    "o": "circle", "s": "square", "D": "diamond", "d": "diamond", "^": "triangle-up",
    "v": "triangle-down", "+": "cross", "P": "cross", "x": "x", "X": "x", "*": "star",
}


def css_color(color: str | None) -> str | None:
    """色の指定を Plotly と matplotlib の両方で通じる形にする（tab:xxx → #rrggbb）。"""
    if color is None:
        return None
    c = str(color).strip()
    return TAB_COLORS.get(c, c)


def marker_symbol(marker: str | None, default: str = "triangle-down") -> str:
    """matplotlib のマーカー記号（v, ^, o …）を Plotly の名前にする。"""
    if not marker:
        return default
    return MPL_MARKERS.get(marker, marker if marker in MPL_MARKERS.values() else default)


def tab10(index: int) -> str:
    """matplotlib の tab10 の index 番目の色。"""
    return _TAB10[index % len(_TAB10)]
