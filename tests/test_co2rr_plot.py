"""co2rr-plot のテスト（集計CSVが kaiseki-tool の出力と一致すること・図の JSON のスナップショット）。

ゴールデン（tests/golden/co2rr-plot/）は kaiseki-tool で次のように作った:
    uv run kaiseki co2rr plot <fixture> --output data --out-dir <tmp> [CASES の引数]
（label_order / labels は kaiseki では --config の JSON で渡した）。改行は LF にそろえてある。
"""

from __future__ import annotations

import importlib
import json
import os
import statistics

import pandas as pd
import pytest

from saji.core.plot.checks import non_arial_texts
from saji.core.runner import execute
from saji.core.tool import InputError, InputFile
from saji.techniques import co2rr

from .conftest import FIXTURES, GOLDEN, load_input

MOD = importlib.import_module("saji.tools.co2rr_plot")
DIR = FIXTURES / "co2rr"

# ケース名 → (fixture, saji のパラメータ)。kaiseki の引数は同じ意味のものを渡した。
CASES = {
    "standard-default": ("standard", {}),
    "standard-pattern": ("standard", {"label_pattern": r"pH\d+"}),
    "standard-sem-order": ("standard", {"label_pattern": r"pH\d+", "error": "sem",
                                        "label_order": '["pH11", "pH9", "pH7", "pH13"]',
                                        "labels": {"S03_CupH7r": "pH9"}}),
    "standard-products": ("standard", {"label_pattern": r"pH\d+", "products": "CO,H2,CH4",
                                       "error": "none"}),
    "grouped": ("grouped", {}),
    "grouped-labelcol": ("grouped", {"label_col": "sample_name", "label_pattern": r"pH\d+"}),
    "label_group": ("label_group", {}),
    "preamble": ("preamble", {"label_pattern": r"pH\d+"}),
    "aliases": ("aliases", {"label_pattern": r"pH\d+"}),
    "empty_cells": ("empty_cells", {}),
}

# 図のスナップショット（tests/golden/figures/co2rr-plot-<名前>.json）
FIGURE_CASES = {
    "standard": ("standard", {"label_pattern": r"pH\d+", "ylim2": "-1.9,-1.4"}),
    "total": ("empty_cells", {"error_mode": "total", "title": "Total error", "xlabel": "Catalyst",
                              "label_order": "catC,catA,catB"}),
}


def run_tool(fixture: str, params: dict, **kw):
    return execute(MOD, {"csv": [load_input(DIR / f"{fixture}.csv")]}, params,
                   export_figures=False, **kw)


def run_text(text: str, params: dict | None = None, name: str = "t.csv"):
    return execute(MOD, {"csv": [InputFile(name, text.encode("utf-8"))]}, params or {},
                   export_figures=False)


# ============================================================ ゴールデン
@pytest.mark.parametrize("case", sorted(CASES))
def test_summary_matches_kaiseki(case):
    fixture, params = CASES[case]
    ex = run_tool(fixture, params)
    files = {f.path: f.data for f in ex.files}
    expected = (GOLDEN / "co2rr-plot" / f"{case}-{fixture}_co2rr_summary.csv").read_bytes()
    assert files[f"{fixture}_co2rr_summary.csv"] == expected


@pytest.mark.parametrize("name", sorted(FIGURE_CASES))
def test_figure_snapshot(name):
    """図の JSON のスナップショット（意図して図を変えたときだけ SAJI_UPDATE_SNAPSHOTS=1 で作り直す）。"""
    fixture, params = FIGURE_CASES[name]
    ex = run_tool(fixture, params)
    assert ex.previews[0]["name"] == f"{fixture}_co2rr"
    spec = json.loads(json.dumps(ex.previews[0]["spec"], ensure_ascii=False, allow_nan=False))
    path = GOLDEN / "figures" / f"co2rr-plot-{name}.json"
    if os.environ.get("SAJI_UPDATE_SNAPSHOTS") == "1":
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8", newline="\n")
    assert spec == json.loads(path.read_text(encoding="utf-8"))


# ============================================================ 図の構造
def test_figure_structure_defaults():
    ex = run_tool("standard", {"label_pattern": r"pH\d+"})
    fig = ex.previews[0]["spec"]
    lay = fig["layout"]
    assert lay["barmode"] == "stack"
    assert lay["legend"]["traceorder"] == "reversed"
    assert lay["xaxis"]["type"] == "category"
    assert lay["yaxis"]["title"]["text"] == "Faradaic efficiency / %"
    assert lay["yaxis2"]["overlaying"] == "y" and lay["yaxis2"]["side"] == "right"
    assert lay["yaxis2"]["title"]["text"] == "Potential / V"
    bars = [t for t in fig["data"] if t["type"] == "bar"]
    assert [t["name"] for t in bars] == [co2rr.DISPLAY_NAMES[p] for p in co2rr.DEFAULT_PRODUCTS]
    assert [t["marker"]["color"] for t in bars] == [co2rr.DEFAULT_COLORS[p] for p in co2rr.DEFAULT_PRODUCTS]
    assert all("error_y" in t for t in bars)                 # segment（既定）
    assert bars[0]["x"] == ["pH7", "pH9", "pH11"]
    assert bars[5]["text"] == ["", "", ""]                   # 1-PrOH（< 3 %）は数値を書かない
    pot = fig["data"][-1]
    assert pot["type"] == "scatter" and pot["yaxis"] == "y2" and pot["mode"] == "lines+markers"
    assert pot["marker"]["symbol"] == "square" and pot["line"]["color"] == "#ff7f0e"
    assert pot["error_y"]["array"][0] == pytest.approx(0.098488578017961)
    assert not pot["showlegend"]
    # 既定では Arial で出せない文字（日本語）を含まない
    assert non_arial_texts(fig) == []
    assert ex.result.warnings == []


def test_figure_options():
    ex = run_tool("standard", {"label_pattern": r"pH\d+", "error_mode": "none",
                               "show_values": False, "show_potential": False,
                               "colors": '{"H2": "tab:blue"}', "stack_order": "CO,H2"})
    fig = ex.previews[0]["spec"]
    assert "yaxis2" not in fig["layout"]
    assert [t["name"] for t in fig["data"]] == ["CO", "H<sub>2</sub>"]
    assert fig["data"][1]["marker"]["color"] == "#1f77b4"
    assert all("error_y" not in t and "text" not in t for t in fig["data"])


def test_total_error_bar():
    ex = run_tool("standard", {"label_pattern": r"pH\d+", "error_mode": "total"})
    fig = ex.previews[0]["spec"]
    bars = [t for t in fig["data"] if t["type"] == "bar"]
    assert all("error_y" not in t for t in bars[:-1])
    total = bars[-1]
    assert total["y"] == [0.0, 0.0, 0.0] and not total["showlegend"]
    agg = ex.result.data["groups"][0]
    expect = sum(agg[f"{p}_err"] ** 2 for p in co2rr.DEFAULT_PRODUCTS) ** 0.5
    assert total["error_y"]["array"][0] == pytest.approx(expect)


def test_japanese_label_warns():
    ex = run_tool("standard", {"ylabel": "ファラデー効率 / %"})
    assert any("Arial" in w for w in ex.result.warnings)


def test_render_png_svg():
    ex = execute(MOD, {"csv": [load_input(DIR / "standard.csv")]},
                 {"label_pattern": r"pH\d+", "error_mode": "total"})
    names = {f.path for f in ex.files}
    assert {"standard_co2rr.png", "standard_co2rr.svg", "standard_co2rr.plotly.json",
            "standard_co2rr_data.csv", "standard_co2rr_summary.csv", "manifest.json"} <= names


# ============================================================ 読み込み（kaiseki の test_co2rr から移植）
def test_load_standard():
    df, present, hinted = co2rr.load_co2rr((DIR / "standard.csv").read_text(encoding="utf-8"))
    assert len(df) == 7 and hinted
    assert present == co2rr.DEFAULT_PRODUCTS
    assert "potential" in df.columns


def test_load_empty_cells_are_nan():
    df, _, _ = co2rr.load_co2rr((DIR / "empty_cells.csv").read_text(encoding="utf-8"))
    assert len(df) == 6
    assert df["EtOH"].isna().sum() == 4
    assert df["potential"].isna().sum() == 2
    assert "Unnamed: 11" not in df.columns


def test_load_preamble_and_aliases():
    pre = load_input(DIR / "preamble.csv")
    df, present, hinted = co2rr.load_co2rr(pre.text())
    assert hinted and len(df) == 5 and present == co2rr.DEFAULT_PRODUCTS
    ali = load_input(DIR / "aliases.csv")
    df, present, hinted = co2rr.load_co2rr(ali.text())
    assert not hinted                           # 別名の列名はアンカーに当たらない → 先頭行がヘッダ
    assert present == co2rr.DEFAULT_PRODUCTS
    assert list(df.columns[:2]) == ["sample_id", "sample_name"]
    assert df["C2H4"].iloc[0] == 24.8 and df["potential"].iloc[0] == -1.52


def test_assign_labels_by_pattern():
    df = pd.DataFrame({"sample_id": ["a", "b", "c"],
                       "sample_name": ["reCupH7fA", "reCupH7r", "reCupH9fA"]})
    out = co2rr.assign_labels(df, label_pattern=r"pH\d+")
    assert list(out["label"]) == ["pH7", "pH7", "pH9"]


def test_assign_labels_map_overrides():
    df = pd.DataFrame({"sample_id": ["a", "b"], "sample_name": ["x", "y"]})
    out = co2rr.assign_labels(df, label_map={"a": "g1"})
    assert list(out["label"]) == ["g1", "y"]


def test_assign_labels_prefers_group_over_label():
    df = pd.DataFrame({"label": ["pH7-01", "pH7-02", "pH9-01"], "group": ["pH7", "pH7", "pH9"],
                       "H2": [1.0, 2.0, 3.0]})
    assert list(co2rr.assign_labels(df)["label"]) == ["pH7", "pH7", "pH9"]


def test_explicit_label_col_beats_group():
    df = pd.DataFrame({"group": ["g1", "g1"], "mine": ["A", "B"]})
    assert list(co2rr.assign_labels(df, label_col="mine")["label"]) == ["A", "B"]


def test_pattern_with_blank_label_does_not_crash():
    df = pd.DataFrame({"sample_name": ["apH7", None]})
    out = co2rr.assign_labels(df, label_pattern=r"pH\d+")
    assert out["label"].iloc[0] == "pH7" and pd.isna(out["label"].iloc[1])


def test_group_without_sample_id():
    ex = run_tool("label_group", {})
    groups = ex.result.data["groups"]
    assert [g["label"] for g in groups] == ["gA", "gB", "gC"]
    assert [g["n"] for g in groups] == [2, 1, 2]
    assert groups[0]["H2"] == 15.0


def test_aggregate_mean_and_error():
    df = pd.DataFrame({"sample_id": ["a", "b"], "label": ["g", "g"], "H2": [10.0, 20.0],
                       "CO": [30.0, 30.0], "potential": [-1.0, -1.2]})
    row = co2rr.aggregate(df, ["H2", "CO"], error="std").iloc[0]
    assert row["n"] == 2 and row["H2"] == 15.0 and row["CO"] == 30.0 and row["CO_err"] == 0.0
    assert row["H2_err"] == pytest.approx(statistics.stdev([10.0, 20.0]))
    assert row["potential"] == pytest.approx(-1.1)
    sem = co2rr.aggregate(df, ["H2"], error="sem").iloc[0]
    assert sem["H2_err"] == pytest.approx(statistics.stdev([10.0, 20.0]) / 2 ** 0.5)


def test_aggregate_single_row_zero_error():
    df = pd.DataFrame({"sample_id": ["a"], "label": ["g"], "H2": [10.0]})
    assert co2rr.aggregate(df, ["H2"], error="std").iloc[0]["H2_err"] == 0.0


def test_parse_name_list():
    assert co2rr.parse_name_list("a, b,,c") == ["a", "b", "c"]
    assert co2rr.parse_name_list('["a,1", "b"]') == ["a,1", "b"]
    assert co2rr.parse_name_list("") is None


# ============================================================ 警告・入力の誤り
def test_warnings_blank_label_and_order():
    ex = run_tool("empty_cells", {"label_order": "catA,catX"})
    w = " ".join(ex.result.warnings)
    assert "空欄の 1 行" in w and "catX" in w and "catB" in w and "catC" in w
    assert [g["label"] for g in ex.result.data["groups"]] == ["catA"]


def test_label_col_not_loaded_warns():
    ex = run_tool("standard", {"label_col": "nothere"})
    assert any("label_col" in w for w in ex.result.warnings)


def test_numeric_labels_stay_categorical():
    ex = run_text("group,H2,CO\n7,10,20\n9,30,40\n11,5,5\n")
    fig = ex.previews[0]["spec"]
    assert fig["data"][0]["x"] == ["7", "9", "11"]
    assert fig["layout"]["xaxis"]["type"] == "category"
    assert "yaxis2" not in fig["layout"]          # 電位の列なし


@pytest.mark.parametrize("text,params", [
    ("a,b\n1,2\n", {}),                                        # 生成物の列が無い
    ("sample_id,H2\nx,1\n", {"label_pattern": "("}),           # 正規表現の誤り
    ("sample_id,H2\nx,1\n", {"label_order": "nothing"}),       # 集計できる群が無い
    ("sample_id,H2\nx,1\n", {"labels": "[1, 2]"}),             # 辞書でない
    ("H2,CO\n1,2\n", {}),                                      # ラベル元の列が無い
])
def test_input_errors(text, params):
    with pytest.raises(InputError):
        run_text(text, params)
