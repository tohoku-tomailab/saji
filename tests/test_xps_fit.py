"""xps-fit のテスト。

kaiseki-tool の xps fit は図しか出さないので、図の元になる数値（prepare_fit_traces /
_prepare_overlay の戻り）を kaiseki-tool で JSON にしたもの（tests/golden/xps-fit/、作り方は
tests/fixtures/xps/kaiseki_golden.py）と一致することを確かめる。
図の JSON 全体は tests/golden/figures/ のスナップショットと比べる
（作り直すときは ``uv run python -m tests.test_xps_fit``）。
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from saji import registry
from saji.core.runner import execute
from saji.core.tool import InputError, InputFile
from saji.techniques.xps import fit as xf

from .conftest import FIXTURES, GOLDEN, load_input

FIT = FIXTURES / "xps" / "fit"
PH7, PH9, PH11 = "fit_O1s_pH7.csv", "fit_O1s_pH9_bom.csv", "fit_O1s_pH11_preamble.csv"

# kaiseki_golden.py の FIT_CASES と同じ条件
CASES = {
    "pH7_default": (PH7, None, False, {}),
    "pH7_window_annotate": (PH7, [527, 535], True, {
        "residual_mode": "panel", "annotate_peaks": True, "peak_labels": ["lattice O", "OH", "H2O"],
        "peak_annotate_offsets": [None, [-40, None]]}),
    "pH9_bom_outside_fit": (PH9, [526, 526.9], False, {"annotate_peaks": True}),
    "pH9_bom_default": (PH9, None, False, {}),
    "pH11_preamble": (PH11, None, True, {
        "residual_mode": "none", "peak_colors": ["#000001", "#000002"], "fill_peaks": False,
        "peak_labels": {"Comp B": "OH"}}),
}

# 同じ条件を xps-fit のパラメータで書いたもの（図の系列の数値をゴールデンと比べる）
TOOL_CASES = {
    "pH7_default": (PH7, {}),
    "pH7_window_annotate": (PH7, {
        "xlim": "527,535", "normalize": "on", "residual": "panel", "annotate_peaks": True,
        "peak_labels": "lattice O,OH,H2O",
        "settings": '{"peak_annotate_offsets": [null, [-40, null]]}'}),
    "pH9_bom_default": (PH9, {}),
    "pH11_preamble": (PH11, {"normalize": "on", "residual": "none", "fill_peaks": False,
                             "peak_colors": "#000001,#000002", "peak_labels": '{"Comp B": "OH"}'}),
}

SNAPSHOTS = {
    "xps-fit-single": ([PH7], {"xlim": "526,538", "annotate_peaks": True,
                               "peak_labels": "lattice O,OH,H2O", "title": "O 1s"}),
    "xps-fit-panel-residual": ([PH7, PH9], {"residual": "panel", "markers": True}),
    "xps-fit-overlay": ([PH7, PH9, PH11], {"overlay": True, "offset_step": 1.3, "annotate_peaks": True,
                                           "peak_labels": "lattice O,OH,H2O",
                                           "settings": '{"sample_label_pos": [0.98, 0.55]}'}),
}


def _golden(name):
    return json.loads((GOLDEN / "xps-fit" / f"{name}.json").read_text(encoding="utf-8"))


def _arr(a):
    if a is None:
        return None
    return [None if not math.isfinite(v) else float(v) for v in np.asarray(a, dtype=float)]


def _trace(t):
    if t is None:
        return None
    return {
        "kind": t["kind"], "label": t["label"], "color": t["color"], "dash": t["dash"],
        "width": t["width"], "in_legend": t["in_legend"], "annotate": t["annotate"],
        "x": _arr(t["x"]), "y": _arr(t["y"]), "fill_base": _arr(t["fill_base"]),
        "apex": None if t["apex"] is None else list(t["apex"]),
        "apex_ceiling": t["apex_ceiling"], "annotate_offset": t["annotate_offset"],
    }


def _prepared(p):
    return json.loads(json.dumps({"mode": p["mode"], "residual_zero": p["residual_zero"],
                                  "main": [_trace(t) for t in p["main"]],
                                  "residual": _trace(p["residual"])}))


def _run(files, params, export=False):
    mod = registry.get("xps-fit")
    return execute(mod, {"fit": [load_input(FIT / f) for f in files]}, params, export_figures=export)


# ============================================================ kaiseki-tool との一致
@pytest.mark.parametrize("case", sorted(CASES))
def test_prepare_matches_kaiseki(case):
    fname, x_range, normalize, settings = CASES[case]
    data = xf.load_fit_csv((FIT / fname).read_bytes())
    p = xf.prepare_fit_traces(data, x_range=x_range, normalize=normalize, settings=settings)
    assert _prepared(p) == _golden(case)


def test_overlay_layers_match_kaiseki():
    settings = {"residual_mode": "offset", "annotate_peaks": True, "peak_labels": ["lattice O", "OH"]}
    prepared = [xf.prepare_fit_traces(xf.load_fit_csv((FIT / f).read_bytes()), x_range=[527, 535],
                                      normalize=True, settings=settings) for f in (PH7, PH9, PH11)]
    layers = xf.stack_layers(prepared, offset_step=1.3, annotate_on="all")
    golden = _golden("overlay")
    assert [lay["offset"] for lay in layers] == [g["offset"] for g in golden]
    for lay, g in zip(layers, golden):
        assert _prepared(lay["prepared"]) == g["prepared"]


def _named(fig):
    """図の系列を名前で引く（塗りの下端は「名前 (fill base)」）。"""
    return {t["name"]: t for t in fig["data"]}


@pytest.mark.parametrize("case", sorted(TOOL_CASES))
def test_figure_traces_match_kaiseki(case):
    fname, params = TOOL_CASES[case]
    exe = _run([fname], params)
    assert not exe.result.warnings
    fig = exe.previews[0]["spec"]
    by_name = _named(fig)
    g = _golden(case)
    expected = g["main"] + ([g["residual"]] if g["residual"] else [])
    assert len([t for t in fig["data"] if not t["name"].endswith("(fill base)")]) == len(expected)
    for tr in expected:
        drawn = by_name[tr["label"]]
        assert drawn["x"] == tr["x"] and drawn["y"] == tr["y"], tr["label"]
        assert drawn["line"]["color"] == tr["color"]
        if tr["fill_base"] is not None:
            assert drawn["fill"] == "tonexty"
            assert by_name[f"{tr['label']} (fill base)"]["y"] == tr["fill_base"]
    # 凡例は kaiseki-tool と同じ並び（Spectrum → Composite → Background → ピーク → Residual）
    shown = [t["name"] for t in reversed(fig["data"]) if t["showlegend"]]
    assert shown == [t["label"] for t in expected if t["in_legend"]]
    assert fig["layout"]["legend"]["traceorder"] == "reversed"


# ============================================================ 図の構造
def test_single_panel_annotations_and_axes():
    exe = _run(*SNAPSHOTS["xps-fit-single"])
    fig = exe.previews[0]["spec"]
    lay = fig["layout"]
    assert lay["title"]["text"] == "O 1s"
    assert lay["xaxis"]["range"] == [538.0, 526.0]
    anns = lay["annotations"]
    assert [a["text"] for a in anns] == ["lattice O", "OH", "H2O"]
    assert all(a["showarrow"] and a["ay"] < 0 for a in anns)
    # 頂点（背景を引いた成分の最大）を指す
    peaks = exe.result.data["files"][0]["peaks"]
    assert [(a["x"], a["y"]) for a in anns] == [(p["apex_x"], p["apex_y"]) for p in peaks]
    assert [p["column"] for p in peaks] == ["[1/1]", "[2/1]", "[3/1]"]
    # 注釈用に y 上端を広げている（範囲を明示）
    assert lay["yaxis"]["autorange"] is False
    # ピークは図中で指し示すので凡例から外れる
    assert [t["name"] for t in reversed(fig["data"]) if t["showlegend"]] == [
        "Spectrum", "Composite", "Background", "Residual"]
    # 残差（offset）の 0 基準線
    assert len(lay["shapes"]) == 1 and lay["shapes"][0]["line"]["dash"] == "dot"


def test_panel_residual_layout():
    exe = _run(*SNAPSHOTS["xps-fit-panel-residual"])
    lay = exe.previews[0]["spec"]["layout"]
    # パネル1: 本体 (x, y) + 残差 (x2, y2)、パネル2: 本体 (x3, y3) + 残差 (x4, y4)
    assert lay["yaxis2"]["domain"][0] > lay["yaxis"]["domain"][1]            # 残差は本体の上
    assert lay["yaxis2"]["domain"][0] - lay["yaxis"]["domain"][1] < 0.02     # ほぼ密着
    assert lay["yaxis"]["domain"][0] > lay["yaxis4"]["domain"][1]            # 1枚目が上
    assert lay["xaxis2"]["showticklabels"] is False
    assert lay["xaxis2"]["autorange"] == "reversed" and lay["xaxis3"]["autorange"] == "reversed"
    assert [a["text"] for a in lay["annotations"]] == ["fit_O1s_pH7", "fit_O1s_pH9_bom"]
    assert exe.result.data["residual_mode"] == "panel"


def test_overlay_structure():
    exe = _run(*SNAPSHOTS["xps-fit-overlay"])
    fig = exe.previews[0]["spec"]
    lay = fig["layout"]
    assert exe.result.data["normalize"] is True and exe.result.data["residual_mode"] == "none"
    texts = [a["text"] for a in lay["annotations"]]
    # ピーク注釈は既定で一番上の段（pH11）だけ、段ラベルはファイル名
    assert texts == ["lattice O", "OH", "fit_O1s_pH7", "fit_O1s_pH9_bom", "fit_O1s_pH11_preamble"]
    labels = [a for a in lay["annotations"] if a["xref"] == "paper"]
    assert all(a["xanchor"] == "right" and a["x"] == 0.98 for a in labels)
    assert [a["y"] for a in labels] == pytest.approx([0.55 * 1.3, 1.3 + 0.55 * 1.3, 2.6 + 0.55 * 1.3])
    # 段ごとの 0 基準線
    assert [s["y0"] for s in lay["shapes"]] == pytest.approx([0.0, 1.3, 2.6])
    # 成分の凡例は1組だけ
    assert [t["name"] for t in reversed(fig["data"]) if t["showlegend"]] == [
        "Spectrum", "Composite", "Background"]
    assert "yaxis2" not in lay


def test_titles_and_file_settings():
    exe = _run([PH7, PH9], {"titles": "pH 7", "settings": json.dumps(
        {"files": {"fit_O1s_pH9_bom.csv": {"title": "pH 9", "peak_labels": ["A", "B"]}}})})
    lay = exe.previews[0]["spec"]["layout"]
    assert [a["text"] for a in lay["annotations"]] == ["pH 7", "pH 9"]
    assert [p["label"] for p in exe.result.data["files"][1]["peaks"]] == ["A", "B"]


def test_outside_fit_window_skips_annotation():
    exe = _run([PH9], {"xlim": "526,526.9", "annotate_peaks": True})
    lay = exe.previews[0]["spec"]["layout"]
    assert lay["annotations"] == []
    assert [p["apex_x"] for p in exe.result.data["files"][0]["peaks"]] == [None, None]


def test_settings_validation():
    with pytest.raises(InputError, match="peak_labels"):
        _run([PH7], {"settings": '{"peak_labels": ["a"]}'})
    exe = _run([PH7], {"settings": '{"dpi": 300, "foo": 1}'})
    assert any("dpi" in w for w in exe.result.warnings)
    assert any("foo" in w for w in exe.result.warnings)


def test_bad_file_is_skipped_with_warning():
    mod = registry.get("xps-fit")
    exe = execute(mod, {"fit": [load_input(FIT / PH7), InputFile("only_energy.csv", b"Energy\n535\n534\n")]},
                  {}, export_figures=False)
    assert any("only_energy.csv" in w for w in exe.result.warnings)
    with pytest.raises(InputError):
        execute(mod, {"fit": [InputFile("only_energy.csv", b"Energy\n535\n534\n")]},
                {"overlay": True}, export_figures=False)


def test_exported_figure_files():
    exe = _run([PH7], {}, export=True)
    names = {f.path for f in exe.files}
    assert {"xps_fit.png", "xps_fit.svg", "xps_fit.plotly.json", "xps_fit_data.csv"} <= names
    assert not exe.result.warnings


# ============================================================ 単体テスト（kaiseki-tool の tests/test_xps_fit.py から移植）
SAMPLE = (b"Energy,Spectrum,Composite spectrum,Background,Residual,[1/1],[2/1]\n"
          b"535.0,12.0,11.0,10.0,1.0,10.5,10.5\n534.0,20.0,18.0,10.0,2.0,14.0,14.0\n"
          b"533.0,40.0,42.0,10.0,-2.0,30.0,22.0\n532.0,25.0,26.0,10.0,-1.0,20.0,16.0\n"
          b"531.0,13.0,12.0,10.0,1.0,11.0,11.0\n")


def _kinds(traces):
    return [t["kind"] for t in traces]


def test_load_fit_csv_splits_components():
    d = xf.load_fit_csv(SAMPLE)
    assert list(d["x"]) == [535.0, 534.0, 533.0, 532.0, 531.0]
    assert list(d["residual"]) == [1.0, 2.0, -2.0, -1.0, 1.0]
    assert [p["name"] for p in d["peaks"]] == ["[1/1]", "[2/1]"]


def test_load_fit_csv_robust_to_preamble_aliases_and_cp932():
    text = ("試料名: テスト\n測定日: 2026-01-01\n\n"
            "B.E.,Raw data,Envelope,Comp A,Comp B\n535,12,11,6,5\n534,20,18,10,8\n533,40,42,25,17\n")
    d = xf.load_fit_csv(text.encode("cp932"))
    assert list(d["x"]) == [535.0, 534.0, 533.0]
    assert d["background"] is None
    assert list(d["residual"]) == [1.0, 2.0, -2.0]
    assert [q["name"] for q in d["peaks"]] == ["Comp A", "Comp B"]


def test_load_fit_csv_without_spectrum_columns_raises():
    with pytest.raises(ValueError):
        xf.load_fit_csv(b"Energy\n535\n534\n")


def test_prepare_order_fill_and_residual_modes():
    data = xf.load_fit_csv(SAMPLE)
    p = xf.prepare_fit_traces(data)
    assert _kinds(p["main"]) == ["spectrum", "composite", "background", "peak", "peak"]
    assert list(p["main"][3]["fill_base"]) == [10.0] * 5
    data_min = min(float(np.nanmin(t["y"])) for t in p["main"])
    assert float(np.nanmax(p["residual"]["y"])) < data_min
    assert np.allclose(p["residual"]["y"] - p["residual_zero"], [1.0, 2.0, -2.0, -1.0, 1.0])
    panel = xf.prepare_fit_traces(data, settings={"residual_mode": "panel"})
    assert panel["residual_zero"] == 0.0
    assert xf.prepare_fit_traces(data, settings={"residual_mode": "none"})["residual"] is None
    with pytest.raises(ValueError):
        xf.prepare_fit_traces(data, settings={"residual_mode": "below"})


def test_prepare_annotation_targets():
    p = xf.prepare_fit_traces(xf.load_fit_csv(SAMPLE), settings={
        "annotate_peaks": True, "peak_labels": ["lattice O", "Shoulder"],
        "peak_annotate_offsets": {"[2/1]": [-30, None]}})
    peaks = [t for t in p["main"] if t["kind"] == "peak"]
    assert all(t["annotate"] and not t["in_legend"] for t in peaks)
    assert [t["apex"] for t in peaks] == [(533.0, 30.0), (533.0, 22.0)]
    assert [t["apex_ceiling"] for t in peaks] == [42.0, 42.0]
    assert peaks[1]["annotate_offset"] == [-30, None]


def test_prepare_toggles_keep_fill_base():
    data = xf.load_fit_csv(SAMPLE)
    p = xf.prepare_fit_traces(data, settings={"show_background": False})
    assert "background" not in _kinds(p["main"])
    base = [t for t in p["main"] if t["kind"] == "peak"][0]["fill_base"]
    assert float(np.nanmin(base)) == 10.0


def test_out_of_range_window_is_empty():
    p = xf.prepare_fit_traces(xf.load_fit_csv(SAMPLE), x_range=(100, 200))
    assert p["main"] == [] and p["residual"] is None


def test_shift_prepared_moves_everything_together():
    p = xf.prepare_fit_traces(xf.load_fit_csv(SAMPLE), settings={"annotate_peaks": True})
    moved = xf.shift_prepared(p, 10.0)
    for before, after in zip(p["main"], moved["main"]):
        assert np.allclose(after["y"], before["y"] + 10.0)
        if before["apex"] is not None:
            assert after["apex"] == (before["apex"][0], before["apex"][1] + 10.0)
    assert moved["residual_zero"] == p["residual_zero"] + 10.0
    assert p["main"][0]["y"][0] != moved["main"][0]["y"][0]      # 元の結果は壊さない


def test_annotate_target():
    assert xf.resolve_annotate_target(None, 3) == 2
    assert xf.resolve_annotate_target("bottom", 3) == 0
    assert xf.resolve_annotate_target("all", 3) is None
    assert xf.resolve_annotate_target(4, 3) == 1


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
