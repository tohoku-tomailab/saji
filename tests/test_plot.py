"""図のビルダーと matplotlib 変換器のテスト（許可した要素ごとにエラーなく描けること）。"""

from __future__ import annotations

import json

import pytest

from saji.core.plot import (
    add_annotation, add_bar, add_hline, add_line, add_vline, add_vrect, get_style, new_figure,
    offset_values, panel_domains, set_axis,
)
from saji.core.plot.checks import non_arial_texts
from saji.core.plot.export import figure_to_csv
from saji.core.plot.mpl import html_to_mathtext, render

ST = get_style("slide")
X = [0, 1, 2, 3, 4, 5]
Y = [0, 2, 5, 3, 1, 0]


def fig_lines():
    fig = new_figure(ST, title="Lines", subtitle="sub")
    offs = offset_values(2, 6)
    add_line(fig, X, [y + offs[0] for y in Y], "a", ST, markers=True, marker_symbol="square")
    add_line(fig, X, [y + offs[1] for y in Y], "b", ST, dash="dash", color="#1e33ff")
    add_line(fig, X, [None, 1, 2, float("nan"), 1, 0], "gap", ST, dash="dot")
    add_vline(fig, 2.5, color="#d62728")
    add_hline(fig, 1.0)
    add_vrect(fig, 0.5, 1.5)
    add_annotation(fig, 2, 11, "peak", ST, arrow=True, ay=-40)
    add_annotation(fig, 0.02, 0.95, "label", ST, xref="paper", yref="paper", xanchor="left")
    set_axis(fig, "xaxis", ST, title="Binding energy / eV", reversed=True, range=[5, 0])
    set_axis(fig, "yaxis", ST, title="Intensity", show_ticklabels=False)
    return fig


def fig_fill():
    fig = new_figure(ST)
    add_line(fig, X, [1] * 6, "bg", ST, dash="dash")
    add_line(fig, X, [1 + y for y in Y], "peak", ST, fill="tonexty", fillcolor="rgba(30,51,255,0.25)")
    add_line(fig, X, Y, "zero", ST, fill="tozeroy")
    set_axis(fig, "xaxis", ST, title="x", range=[None, 4])
    set_axis(fig, "yaxis", ST, title="y", log=True, range=[0.1, 10])
    return fig


def fig_bars():
    fig = new_figure(ST, legend="outside")
    fig["layout"]["barmode"] = "stack"
    cats = ["pH7", "pH9"]
    add_bar(fig, cats, [20, 30], "H<sub>2</sub>", color="#bfbfbf", error=[2, 3], text=["20.0", "30.0"])
    add_bar(fig, cats, [40, 10], "CO", color="#ffd400", error=[1, 0])
    add_line(fig, cats, [-1.5, -1.8], "Potential", ST, markers=True, yaxis="y2", color="#ff7f0e")
    set_axis(fig, "xaxis", ST)
    set_axis(fig, "yaxis", ST, title="FE / %", range=[0, 120])
    set_axis(fig, "yaxis2", ST, title="E / V", overlaying="y", side="right")
    return fig


def fig_panels():
    fig = new_figure(ST, height=900)
    doms = panel_domains(2, ratios=[3, 1])
    add_line(fig, X, Y, "main", ST, xaxis="x", yaxis="y")
    add_line(fig, X, [0.1, -0.1, 0.2, 0, -0.2, 0.1], "residual", ST, xaxis="x2", yaxis="y2")
    add_vline(fig, 2, yref="y2 domain", xref="x2")
    set_axis(fig, "xaxis", ST, anchor="y", show_ticklabels=False, reversed=True)
    set_axis(fig, "yaxis", ST, title="Main", domain=doms[0], anchor="x")
    set_axis(fig, "xaxis2", ST, title="Energy", anchor="y2", reversed=True)
    set_axis(fig, "yaxis2", ST, title="Res.", domain=doms[1], anchor="x2")
    return fig


@pytest.mark.parametrize("make", [fig_lines, fig_fill, fig_bars, fig_panels])
@pytest.mark.parametrize("fmt", ["svg", "png"])
def test_render_each_element(make, fmt):
    fig = make()
    json.dumps(fig, allow_nan=False)             # JSON にできる（NaN は null に）
    data = render(fig, fmt)
    assert data.startswith(b"\x89PNG") if fmt == "png" else b"<svg" in data[:500]


def test_svg_is_deterministic():
    assert render(fig_lines(), "svg") == render(fig_lines(), "svg")


def test_figure_csv():
    csv = figure_to_csv(fig_bars())
    head = csv.splitlines()[0].split(",")
    assert head[:3] == ["H<sub>2</sub> x", "H<sub>2</sub> y", "H<sub>2</sub> err"]


def test_non_arial_detected():
    fig = new_figure(ST, title="ファラデー効率")
    assert non_arial_texts(fig) == ["ファラデー効率"]
    assert non_arial_texts(fig_lines()) == []


def test_html_to_mathtext():
    assert html_to_mathtext("H<sub>2</sub>O") == "H$_{2}$O"
    assert html_to_mathtext("a<br>b") == "a\nb"
