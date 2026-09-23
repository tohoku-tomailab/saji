"""図の JSON（Plotly 形式）の組み立て補助と、matplotlib への変換器。

  style     … スタイルプリセット・配色・STYLE_PARAM
  builders  … 図・軸・系列・注釈などを組み立てる関数（許可した要素だけを作る）
  mpl       … 図の JSON → SVG / PNG（matplotlib。手法の知識は持たない）
  export    … 図の元データ → CSV
  checks    … Arial で表示できない文字の検出
"""

from .builders import (
    add_annotation,
    add_bar,
    add_hline,
    add_line,
    add_vline,
    add_vrect,
    new_figure,
    offset_values,
    panel_domains,
    set_axis,
    to_jsonable,
)
from .style import SERIES_COLORS, STYLE_PARAM, get_style, series_color, to_rgba

__all__ = [
    "add_annotation", "add_bar", "add_hline", "add_line", "add_vline", "add_vrect",
    "new_figure", "offset_values", "panel_domains", "set_axis", "to_jsonable",
    "SERIES_COLORS", "STYLE_PARAM", "get_style", "series_color", "to_rgba",
]
