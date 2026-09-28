"""xrd-overlay-2（重ね描き＋参照ピークの縦棒パネル）のテスト。

参照ピークは合成（tests/fixtures/xrd/refs/）。上のパネルは xrd-overlay と同じになることも確かめる。
"""

from __future__ import annotations

import json
import os

import pytest

from saji import registry
from saji.core.runner import execute
from saji.core.tool import InputError, InputFile
from saji.techniques import xrd

from .conftest import FIXTURES, GOLDEN, load_input

XY = ["case2-synthA_processed.xy", "case2-synthB_processed.xy"]
REFS = ["ref_a.json", "ref_bc.json"]
SNAPSHOT = GOLDEN / "figures" / "xrd-overlay-2.json"


def _run(params, refs=REFS, xy=XY, tool="xrd-overlay-2"):
    files = {"xy": [load_input(GOLDEN / "xrd-process" / n) for n in xy]}
    if refs:
        files["refs"] = [load_input(FIXTURES / "xrd" / "refs" / n) for n in refs]
    return execute(registry.get(tool), files, params, export_figures=False)


def test_load_refs_normalizes_and_accepts_list():
    a = xrd.load_refs((FIXTURES / "xrd" / "refs" / "ref_a.json").read_bytes())
    assert [r["name"] for r in a] == ["PhaseA"]
    assert a[0]["peaks"][0]["intensity"] == pytest.approx(100.0)
    assert a[0]["peaks"][1]["intensity"] == pytest.approx(45 / 99 * 100)
    assert a[0]["peaks"][0]["hkl"] == "1 1 1"
    bc = xrd.load_refs((FIXTURES / "xrd" / "refs" / "ref_bc.json").read_bytes())
    assert [r["label"] for r in bc] == ["PhaseB", "PhaseC"]      # label の省略は name
    assert bc[1]["peaks"][0]["intensity"] == 100.0              # intensity の省略は 100


@pytest.mark.parametrize("doc", ['{"name": "X"}', '{"name": "X", "peaks": []}',
                                 '{"name": "X", "peaks": [{"intensity": 5}]}', '[1]'])
def test_bad_refs_are_input_errors(doc):
    with pytest.raises(InputError, match="bad.json"):
        execute(registry.get("xrd-overlay-2"),
                {"xy": [load_input(GOLDEN / "xrd-process" / XY[0])],
                 "refs": [InputFile(name="bad.json", data=doc.encode())]}, {},
                export_figures=False)


def test_panels_and_sticks():
    ex = _run({"xlim": "30,80", "ref_min_intensity": 5})
    fig = ex.previews[0]["spec"]
    lay = fig["layout"]
    # 上のパネル + 参照3枚（ファイルの順、ファイル内の順）
    assert [lay[f"yaxis{i}"]["domain"][1] > lay[f"yaxis{i}"]["domain"][0] for i in (2, 3, 4)] == [True] * 3
    doms = [lay["yaxis"]["domain"]] + [lay[f"yaxis{i}"]["domain"] for i in (2, 3, 4)]
    assert doms[0][1] == 1.0 and doms[-1][0] == pytest.approx(0.0)
    for upper, lower in zip(doms, doms[1:]):
        assert upper[0] == pytest.approx(lower[1])              # 隙間なく密着
    # x 軸: 範囲は全パネル共通、数値と軸名は一番下だけ
    for k in ("xaxis", "xaxis2", "xaxis3", "xaxis4"):
        assert lay[k]["range"] == [30.0, 80.0]
    assert [lay[k]["showticklabels"] for k in ("xaxis", "xaxis2", "xaxis3", "xaxis4")] == [False, False, False, True]
    assert "title" not in lay["xaxis"] and lay["xaxis4"]["title"]["text"] == "2θ (deg)"
    # 縦棒: 範囲外（95°）と弱い線（3 → 3.03 < 5）は描かない。PhaseC（10°）は線なし → 警告
    # （線が無くてもパネルが作られるよう、空の系列は置く）
    sticks = {t["name"]: t for t in fig["data"] if t.get("yaxis") != "y"}
    assert set(sticks) == {"Phase<sub>A</sub>", "PhaseB", "PhaseC"}
    assert sticks["PhaseC"]["x"] == [] and sticks["PhaseC"]["yaxis"] == "y4"
    a = sticks["Phase<sub>A</sub>"]
    assert a["x"] == [43.3, 43.3, None, 50.4, 50.4, None]
    assert a["y"][:2] == [0.0, 100.0] and a["showlegend"] is False
    assert sticks["PhaseB"]["line"]["color"] == "#d62728"     # tab:red
    assert [r["n_shown"] for r in ex.result.data["refs"]] == [2, 2, 0]
    assert any("PhaseC" in w for w in ex.result.warnings)
    # 物質名はパネルの右上（そのパネルの domain 座標）
    labels = [a for a in lay["annotations"] if a["xref"].endswith("domain")]
    assert [(a["text"], a["xref"], a["yref"]) for a in labels] == [
        ("Phase<sub>A</sub>", "x2 domain", "y2 domain"), ("PhaseB", "x3 domain", "y3 domain"),
        ("PhaseC", "x4 domain", "y4 domain")]
    # 縦棒の最大（100）は文字の下に収まる
    for i in (2, 3, 4):
        assert lay[f"yaxis{i}"]["range"][1] > 100


def test_main_panel_matches_xrd_overlay():
    """上のパネルの系列は xrd-overlay（ピーク表なし）と同じ。"""
    params = {"normalize_each": True, "bottom_up": True}
    ours = _run(params).previews[0]["spec"]
    theirs = _run(params, refs=None, tool="xrd-overlay").previews[0]["spec"]
    main = [t for t in ours["data"] if t.get("yaxis", "y") == "y"]
    assert main == theirs["data"]
    assert ours["layout"]["yaxis"]["range"] == theirs["layout"]["yaxis"]["range"]
    assert ours["layout"]["height"] > theirs["layout"]["height"]


def test_without_refs_is_plain_overlay():
    ex = _run({}, refs=None)
    lay = ex.previews[0]["spec"]["layout"]
    assert "yaxis2" not in lay and lay["xaxis"]["showticklabels"] is True
    assert lay["xaxis"]["title"]["text"] == "2θ (deg)"


def test_empty_ref_panel_is_rendered():
    """描ける線が無い参照（PhaseC）のパネルも PNG/SVG で作られ、一番下の x 軸の数値・軸名が残る。"""
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    from saji.core.plot.mpl import _Renderer

    spec = _run({"xlim": "30,80"}).previews[0]["spec"]
    mfig = Figure()
    FigureCanvasAgg(mfig)
    r = _Renderer(spec, mfig)
    r.draw()
    assert set(r.axes) == {("x", "y"), ("x2", "y2"), ("x3", "y3"), ("x4", "y4")}
    bottom = r.axes[("x4", "y4")]
    assert bottom.get_xlabel() == "2θ (deg)"
    assert any(t.get_text() for t in bottom.get_xticklabels())
    assert "PhaseC" in [t.get_text() for t in bottom.texts]


@pytest.mark.parametrize("tool", ["xrd-overlay", "xrd-overlay-2"])
def test_yticks_hidden_by_default(tool):
    """y はオフセットを足した値なので、既定では目盛の数値を出さない（show_yticks で出す）。"""
    refs = REFS if tool == "xrd-overlay-2" else None
    for params, shown in (({}, False), ({"show_yticks": True}, True)):
        lay = _run({"normalize_each": True, **params}, refs=refs, tool=tool).previews[0]["spec"]["layout"]
        assert lay["yaxis"]["showticklabels"] is shown
        assert lay["yaxis"]["ticks"] == "inside"          # 目盛線は残す


def test_figure_snapshot():
    """図の JSON のスナップショット（意図して図を変えたときだけ SAJI_UPDATE_SNAPSHOTS=1 で作り直す）。"""
    ex = _run({"xlim": "30,80"})
    spec = json.loads(json.dumps(ex.previews[0]["spec"], ensure_ascii=False))
    if os.environ.get("SAJI_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8", newline="\n")
    assert spec == json.loads(SNAPSHOT.read_text(encoding="utf-8"))
