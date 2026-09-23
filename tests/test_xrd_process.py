"""xrd-process のゴールデンテスト（kaiseki-tool の出力と一致すること）。"""

from __future__ import annotations

import pytest

from saji import registry
from saji.core.runner import execute

from .conftest import FIXTURES, GOLDEN, load_input

CASES = {
    "case1": {"bg": "arpls", "smooth": "savgol", "norm": "max", "norm_target": 100},
    "case2": {"bg": "snip", "smooth": "gaussian", "norm": "area", "bin": 5},
    "case3": {"bg": "none", "smooth": "moving_average", "norm": "reference", "norm_ref_pos": 50.4},
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_matches_golden(case):
    mod = registry.get("xrd-process")
    raw = [load_input(FIXTURES / "xrd" / f"{n}.TXT") for n in ("synthA", "synthB")]
    ex = execute(mod, {"raw": raw}, CASES[case], export_figures=False)
    files = {f.path: f.data for f in ex.files}
    for stem in ("synthA", "synthB"):
        expected = (GOLDEN / "xrd-process" / f"{case}-{stem}_processed.xy").read_bytes()
        assert files[f"{stem}_processed.xy"] == expected


def test_peaks_and_figure():
    mod = registry.get("xrd-process")
    ex = execute(mod, {"raw": [load_input(FIXTURES / "xrd" / "synthA.TXT")],
                       "peaks": [load_input(FIXTURES / "xrd" / "peaks.json")]},
                 {"norm": "max", "smooth": "savgol"}, export_figures=False)
    info = ex.result.data["files"][0]
    assert info["peaks_found"] == ["Cu(111)", "Cu(200)", "Cu(220)"]
    assert info["peaks_missed"] == ["TiO2(101)"]
    fig = ex.previews[0]["spec"]
    assert fig["layout"]["yaxis2"]["overlaying"] == "y"
    assert [a["text"] for a in fig["layout"]["annotations"]] == ["Cu(111)", "Cu(200)", "Cu(220)"]
    assert not ex.result.warnings
