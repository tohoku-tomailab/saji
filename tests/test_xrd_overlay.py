"""xrd-overlay のゴールデンテスト（kaiseki-tool の xrd overlay と一致すること）。

期待値 tests/golden/xrd-overlay/*.json は kaiseki-tool で作ったもの（作り方は同じフォルダの
make_golden.py）。入力は tests/golden/xrd-process/*.xy（kaiseki の処理済み .xy）。
"""

from __future__ import annotations

import json
import os

import pytest

from saji import registry
from saji.core.runner import execute
from saji.techniques import xrd

from .conftest import FIXTURES, GOLDEN, load_input

CASES = sorted(p.stem for p in (GOLDEN / "xrd-overlay").glob("*.json"))
SNAPSHOT = GOLDEN / "figures" / "xrd-overlay.json"


def _run(inputs, params, peaks=None):
    mod = registry.get("xrd-overlay")
    files = {"xy": [load_input(GOLDEN / "xrd-process" / n) for n in inputs]}
    if peaks:
        files["peaks"] = [load_input(FIXTURES / "xrd" / peaks)]
    return execute(mod, files, params, export_figures=False)


def _golden(case):
    return json.loads((GOLDEN / "xrd-overlay" / f"{case}.json").read_text(encoding="utf-8"))


def _flat(v):
    return [w for x in v for w in _flat(x)] if isinstance(v, (list, tuple)) else [v]


def _approx(a, b):
    return pytest.approx(_flat(b), rel=1e-9, abs=1e-9) == _flat(a)


@pytest.mark.parametrize("case", CASES)
def test_matches_kaiseki(case):
    g = _golden(case)
    ex = _run(g["inputs"], g["params"], g["peaks"])
    data = ex.result.data
    fig = ex.previews[0]["spec"]
    assert ex.previews[0]["name"] == "overlay"

    # 系列: 順番・ラベル・色・オフセット・y 値（オフセット込み）・ピーク検出
    lines = [t for t in fig["data"] if t["mode"] == "lines"]
    assert len(lines) == len(g["traces"]) == len(data["traces"])
    for gt, tr, info in zip(g["traces"], lines, data["traces"]):
        assert info["file"] == gt["file"]
        assert tr["name"] == info["label"] == gt["label"]
        assert tr["line"]["color"] == info["color"] == gt["color"]
        assert _approx(info["offset"], gt["offset"])
        y = tr["y"]
        assert len(y) == gt["y"]["n"]
        assert _approx(min(y), gt["y"]["min"]) and _approx(max(y), gt["y"]["max"])
        assert pytest.approx(gt["y"]["sum"], rel=1e-9) == sum(y)
        assert _approx(y[::50], gt["y"]["sample"])
        found = {p["material"]: p for p in info["peaks_found"]}
        for gp in gt["peaks"]:
            assert (gp["material"] in found) == gp["found"]
            if gp["found"]:
                assert _approx([found[gp["material"]]["x"], found[gp["material"]]["y"]],
                               [gp["x"], gp["y"]])

    # ピークのマーカー位置・物質名の位置（段積み）
    markers = [[x, y] for t in fig["data"] if t["mode"] == "markers"
               for x, y in zip(t["x"], t["y"])]
    assert _approx(markers, g["markers"])
    anns = fig["layout"]["annotations"]
    assert [a["text"] for a in anns] == [lb["text"] for lb in g["labels"]]
    assert _approx([[a["x"], a["y"]] for a in anns], [[lb["x"], lb["y"]] for lb in g["labels"]])
    assert [lb["stack_level"] for lb in data["labels"]] == [a["stack_level"] for a in g["laid"]]

    # y 軸の範囲（kaiseki の matplotlib の自動範囲 + 注釈の分）
    assert _approx(fig["layout"]["yaxis"]["range"], g["ylim"])

    # 基線（系列ごと）と参照位置の縦線
    shapes = fig["layout"]["shapes"]
    hlines = [s for s in shapes if s["xref"] == "paper"]
    vlines = [s for s in shapes if s["yref"] == "paper"]
    assert _approx([s["y0"] for s in hlines], [t["offset"] for t in g["traces"]])
    assert all(s["opacity"] == 0.4 for s in hlines)
    n_peaks = len(g["traces"][0]["peaks"])
    assert len(vlines) == (n_peaks if g["params"].get("peak_guides", True) else 0)


def test_labels_and_legend_order():
    g = _golden("bottomup_norm_top")
    ex = _run(g["inputs"], g["params"], g["peaks"])
    lay = ex.previews[0]["spec"]["layout"]
    assert lay["yaxis"]["title"]["text"] == "Intensity (offset)  [each max-normalized]"
    assert lay["xaxis"]["title"]["text"] == "2θ (deg)"
    assert lay["legend"]["traceorder"] == "reversed"   # 下積みでも凡例は図の上→下
    assert lay["legend"]["xanchor"] == "right"          # 既定は軸内の右上


def test_options_xlim_legend_title():
    ex = _run(["case1-synthA_processed.xy"],
              {"xlim": "30,60", "legend": "outside", "title": "Overlay", "ylabel": "I"})
    lay = ex.previews[0]["spec"]["layout"]
    assert lay["xaxis"]["range"] == [30.0, 60.0]
    assert lay["legend"]["xanchor"] == "left"
    assert lay["title"]["text"] == "Overlay"
    assert lay["yaxis"]["title"]["text"] == "I"
    assert ex.result.data["traces"][0]["offset"] == 0.0


def test_traces_unknown_and_unlisted_warn():
    ex = _run(["case1-synthA_processed.xy", "case1-synthB_processed.xy"],
              {"traces": [{"file": "C:\\data\\case1-synthB_processed.xy"},
                          {"file": "missing.xy"}]})
    assert [t["file"] for t in ex.result.data["traces"]] == ["case1-synthB_processed.xy"]
    assert any("missing.xy" in w for w in ex.result.warnings)
    assert any("case1-synthA_processed.xy" in w for w in ex.result.warnings)


def test_input_errors():
    from saji.core.tool import InputError, InputFile

    mod = registry.get("xrd-overlay")
    xy = [load_input(GOLDEN / "xrd-process" / "case1-synthA_processed.xy")]
    with pytest.raises(InputError):
        execute(mod, {"xy": xy}, {"offset": "abc"}, export_figures=False)
    with pytest.raises(InputError):
        execute(mod, {"xy": xy}, {"traces": {"file": "a"}}, export_figures=False)
    bad = [InputFile("bad.xy", b"not numbers\n1 2 3\n")]
    with pytest.raises(InputError):
        execute(mod, {"xy": bad}, {}, export_figures=False)
    ex = execute(mod, {"xy": xy + bad}, {}, export_figures=False)
    assert any("bad.xy" in w for w in ex.result.warnings)


def test_colormaps_match_matplotlib():
    from matplotlib import colormaps
    from matplotlib.colors import to_hex

    for n in (1, 2, 5, 11, 37):
        cols, name = xrd.assign_colors(n, "viridis")
        assert name == "viridis"
        assert cols == [to_hex(colormaps["viridis"](i / max(1, n - 1))) for i in range(n)]
    assert xrd.assign_colors(20, "tab20")[0] == [to_hex(c) for c in colormaps["tab20"].colors]
    assert xrd.assign_colors(10, "tab10")[0] == [to_hex(c) for c in colormaps["tab10"].colors]
    assert xrd.assign_colors(11, "tab10")[1] == "viridis"   # tab10 で足りなければ viridis
    assert xrd.assign_colors(21, "tab20")[1] == "viridis"


def test_render_and_outputs():
    g = _golden("default")
    mod = registry.get("xrd-overlay")
    files = {"xy": [load_input(GOLDEN / "xrd-process" / n) for n in g["inputs"]],
             "peaks": [load_input(FIXTURES / "xrd" / "peaks.json")]}
    ex = execute(mod, files, {})
    names = sorted(f.path for f in ex.files)
    assert names == ["manifest.json", "overlay.plotly.json", "overlay.png", "overlay.svg",
                     "overlay_data.csv"]
    assert not ex.result.warnings


def test_figure_snapshot():
    """図の JSON のスナップショット（意図して図を変えたときだけ SAJI_UPDATE_SNAPSHOTS=1 で作り直す）。

    ファイルを小さくするため、点数の少ない case2（5 点ビニング）の .xy を使う。
    """
    ex = _run(["case2-synthA_processed.xy", "case2-synthB_processed.xy"],
              {"normalize_each": True}, "peaks_close.json")
    spec = json.loads(json.dumps(ex.previews[0]["spec"], ensure_ascii=False))
    if os.environ.get("SAJI_UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(exist_ok=True)
        SNAPSHOT.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8", newline="\n")
    assert spec == json.loads(SNAPSHOT.read_text(encoding="utf-8"))
