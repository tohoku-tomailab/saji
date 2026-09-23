"""xps-plot のテスト。

kaiseki-tool の xps plot は図しか出さないので、図の元になる数値（prepare_traces の戻り）を
kaiseki-tool で JSON にしたもの（tests/golden/xps-plot/、作り方は
tests/fixtures/xps/kaiseki_golden.py）と、saji の図の系列の x / y が一致することを確かめる。
図の JSON 全体は tests/golden/figures/ のスナップショットと比べる
（作り直すときは ``uv run python -m tests.test_xps_plot``）。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from saji import registry
from saji.core.plot import get_style
from saji.core.runner import execute
from saji.core.tool import InputError, InputFile
from saji.techniques.xps import plot as xp

from .conftest import FIXTURES, GOLDEN, load_input

EXT = FIXTURES / "xps" / "extracted"

# ゴールデンと同じ条件（kaiseki_golden.py の PLOT_CASES に対応）
CASES = {
    "survey": (["sampleA_Survey.csv", "sampleB_Survey.csv"], {}),
    "c1s_window": (["sampleA_C1s.csv", "sampleB_C1s.csv", "sampleC_C1s.csv"],
                   {"xlim": "292,280", "offset_step": 1.5}),
    "no_window_normalize": (["sampleA_C1s.csv", "sampleC_C1s.csv"],
                            {"xlim": "282,290", "window_normalize": False, "offset_step": 2.0}),
}

SNAPSHOTS = {
    "xps-plot-c1s_window": (CASES["c1s_window"][0], {**CASES["c1s_window"][1], "markers": True}),
    "xps-plot-region": (["sampleA_C1s.csv", "sampleA_Survey.csv", "sampleB_C1s.csv",
                         "sampleB_Survey.csv"], {"group_by": "region", "title": "XPS"}),
}


def _run(files, params, export=False):
    mod = registry.get("xps-plot")
    return execute(mod, {"csv": [load_input(EXT / f) for f in files]}, params, export_figures=export)


@pytest.mark.parametrize("case", sorted(CASES))
def test_traces_match_kaiseki(case):
    files, params = CASES[case]
    exe = _run(files, params)
    fig = exe.previews[0]["spec"]
    golden = json.loads((GOLDEN / "xps-plot" / f"{case}.json").read_text(encoding="utf-8"))
    assert [t["name"] for t in fig["data"]] == [g["label"] for g in golden]
    for tr, g in zip(fig["data"], golden):
        assert tr["x"] == g["x"]
        assert tr["y"] == g["y"]
    assert not exe.result.warnings


def test_figure_structure():
    exe = _run(*CASES["c1s_window"])
    fig = exe.previews[0]["spec"]
    lay = fig["layout"]
    assert lay["title"]["text"] == "C1s"                     # 1グループの見出しはファイル名の末尾
    assert lay["xaxis"]["range"] == [292.0, 280.0]           # 結合エネルギー軸は反転
    assert lay["xaxis"]["title"]["text"] == "Binding energy / eV"
    assert lay["yaxis"]["showticklabels"] is False
    assert exe.result.data["groups"][0]["files"][2] == {
        "file": "sampleC_C1s.csv", "label": "sampleC_C1s", "n_points": 121}


def test_group_by_region_makes_panels():
    exe = _run(*SNAPSHOTS["xps-plot-region"])
    fig = exe.previews[0]["spec"]
    lay = fig["layout"]
    assert [g["title"] for g in exe.result.data["groups"]] == ["C1s", "Survey"]
    assert lay["title"]["text"] == "XPS"
    assert [a["text"] for a in lay["annotations"]] == ["C1s", "Survey"]
    assert lay["yaxis"]["domain"][0] > lay["yaxis2"]["domain"][1]     # 1枚目が上
    assert lay["xaxis2"]["anchor"] == "y2" and lay["xaxis2"]["autorange"] == "reversed"
    assert [t["yaxis"] for t in fig["data"]] == ["y", "y", "y2", "y2"]


def test_groups_json_labels_colors_and_unused():
    files = ["sampleA_C1s.csv", "sampleB_C1s.csv", "sampleA_Survey.csv"]
    exe = _run(files, {"groups": json.dumps(
        [[{"file": "sampleB_C1s", "label": "B", "color": "#123456"}, "sampleA_C1s.csv"]])})
    fig = exe.previews[0]["spec"]
    assert [t["name"] for t in fig["data"]] == ["B", "sampleA_C1s"]
    assert fig["data"][0]["line"]["color"] == "#123456"
    assert exe.result.warnings == ["groups に含まれていないので描かなかったファイル: sampleA_Survey.csv"]


def test_axis_ranges_per_panel_and_xlim_override():
    files = SNAPSHOTS["xps-plot-region"][0]
    ranges = json.dumps([{"x_range": [280, 292]}, {"x_range": [0, 600], "y_range": [0, 3]}])
    fig = _run(files, {"group_by": "region", "axis_ranges": ranges}).previews[0]["spec"]
    assert fig["layout"]["xaxis"]["range"] == [292.0, 280.0]
    assert fig["layout"]["xaxis2"]["range"] == [600.0, 0.0]
    assert fig["layout"]["yaxis2"]["range"] == [0.0, 3.0]
    fig = _run(files, {"group_by": "region", "axis_ranges": ranges, "xlim": "284,288"}).previews[0]["spec"]
    assert fig["layout"]["xaxis2"]["range"] == [288.0, 284.0]


def test_empty_window_warns():
    exe = _run(["sampleA_C1s.csv", "sampleA_Survey.csv"], {"xlim": "1200,1300"})
    assert exe.result.warnings[-1] == "描けるデータが1本もありません"
    assert "No valid data" in [a["text"] for a in exe.previews[0]["spec"]["layout"]["annotations"]]


def test_errors_are_input_errors():
    with pytest.raises(InputError):
        _run(["sampleA_C1s.csv"], {"xlim": "280,"})
    with pytest.raises(InputError):
        _run(["sampleA_C1s.csv"], {"groups": '{"a": 1}'})


def test_exported_figure_files():
    exe = _run(*CASES["survey"], export=True)
    names = [f.path for f in exe.files]
    assert {"xps.png", "xps.svg", "xps.plotly.json", "xps_data.csv"} <= set(names)
    assert not exe.result.warnings


# ============================================================ 単体テスト（kaiseki-tool の tests/test_xps.py から移植）
def test_clip_and_renormalize():
    x = np.array([190.0, 189.0, 188.0, 187.0])
    y = np.array([0.1, 0.5, 0.3, 0.9])
    cx, cy = xp.clip_to_x_range(x, y, (188, 190))
    assert list(cx) == [190.0, 189.0, 188.0]
    ry = xp.renormalize_y(cy)
    assert float(ry.min()) == 0.0 and float(ry.max()) == 1.0


def test_prepare_traces_offsets_and_bad_file():
    data = (EXT / "sampleA_C1s.csv").read_bytes()
    entries = [{"name": "a.csv", "data": data, "label": "a"},
               {"name": "bad.csv", "data": b"only\n1\n", "label": "bad"},
               {"name": "b.csv", "data": data, "label": "Cu 2p"}]
    traces, warns = xp.prepare_traces(entries, window_normalize=False, offset_step=2.0)
    assert [t["label"] for t in traces] == ["a", "Cu 2p"]
    assert float(np.min(traces[1]["y"])) >= 4.0     # 3本目（i=2）は +2×offset_step
    assert len(warns) == 1 and "bad.csv" in warns[0]


def test_plot_figure_no_japanese():
    st = get_style("slide")
    fig = xp.plot_figure([[]], st, titles=["t"])
    assert fig["layout"]["annotations"][0]["text"] == "No valid data"


# ============================================================ スナップショット
def _snapshot(name):
    files, params = SNAPSHOTS[name]
    return json.loads(json.dumps(_run(files, params).previews[0]["spec"]))


@pytest.mark.parametrize("name", sorted(SNAPSHOTS))
def test_figure_snapshot(name):
    expected = json.loads((GOLDEN / "figures" / f"{name}.json").read_text(encoding="utf-8"))
    assert _snapshot(name) == expected


if __name__ == "__main__":
    for key in SNAPSHOTS:
        path = GOLDEN / "figures" / f"{key}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(_snapshot(key), ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8", newline="\n")
        print("wrote", path)
