"""xrd-process のゴールデンテスト（kaiseki-tool の出力と一致すること）。"""

from __future__ import annotations

import numpy as np
import pytest

from saji import registry
from saji.core.runner import execute
from saji.core.tool import InputFile
from saji.techniques import xrd

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
        assert_xy_equal(files[f"{stem}_processed.xy"], expected)


def assert_xy_equal(actual: bytes, expected: bytes) -> None:
    """.xy がゴールデンと一致すること。

    ヘッダ（処理条件）と点数は完全一致。値は %.6f の最後の桁（1e-6）の違いまで許す。
    arPLS の線形計算は CPU（BLAS）によって末尾のビットが変わり、丸めの境目で最後の桁が
    1 ずれることがある（GitHub Actions のランナーで実際に起きた）。
    """
    a_lines, e_lines = actual.decode().splitlines(), expected.decode().splitlines()
    assert a_lines[0] == e_lines[0]
    assert len(a_lines) == len(e_lines)
    a = np.loadtxt(a_lines[1:])
    e = np.loadtxt(e_lines[1:])
    np.testing.assert_allclose(a, e, rtol=0, atol=1.5e-6)


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


# ---- SmartLab Studio II の RAS 形式テキスト（*_cps.txt / *_counts.txt）----
# 合成データ（実データではない）。ヘッダは `*KEY "value"` 形式、データ行は「2θ 強度」の2列。
def _ras_text(unit: str | None = "cps", with_xray: bool = True) -> str:
    lines = ['*FILE_SAMPLE "synthRAS"', '*HW_GONIOMETER_NAME "StandardInplane"']
    if with_xray:
        lines += ['*MEAS_COND_XG_CURRENT "200"', '*MEAS_COND_XG_VOLTAGE "45"']
    lines += ['*MEAS_SCAN_AXIS_X "TwoThetaOmega"', '*MEAS_SCAN_START "20.0000"',
              '*MEAS_SCAN_STEP "0.0200"', '*MEAS_SCAN_STOP "20.0400"']
    if unit:
        lines.append(f'*MEAS_SCAN_UNIT_Y "{unit}"')
    lines += ["20.0000 456.8366", "20.0200 465.4362", "20.0400 408.1622", ""]
    return "\n".join(lines)


def test_ras_metadata_and_data():
    x, y, meta = xrd.load_smartlab(_ras_text())
    np.testing.assert_allclose(x, [20.0, 20.02, 20.04])
    np.testing.assert_allclose(y, [456.8366, 465.4362, 408.1622])
    assert meta["Sample"] == "synthRAS"
    assert (meta["Start"], meta["Stop"], meta["Step"]) == ("20.0000", "20.0400", "0.0200")
    assert meta["X-Ray"] == "45kV/200mA"
    assert meta["ScanningMode"] == "TwoThetaOmega"
    assert meta["Unit"] == "cps"
    assert "_kV" not in meta and "_mA" not in meta


def test_ras_missing_fields():
    _, _, meta = xrd.load_smartlab(_ras_text(unit=None, with_xray=False))
    assert "Unit" not in meta and "X-Ray" not in meta
    assert xrd.intensity_label(meta) == "Intensity (counts)"


def test_legacy_txt_metadata_unchanged():
    text = "Sample\tA\nX-Ray\t40kV/30mA\nStart\t20\n\n20\t85\n20.0004\t86\n"
    _, _, meta = xrd.load_smartlab(text)
    assert meta == {"Sample": "A", "X-Ray": "40kV/30mA", "Start": "20"}
    assert xrd.intensity_label(meta) == "Intensity (counts)"


@pytest.mark.parametrize("unit", ["cps", "counts"])
def test_ras_unit_in_ylabel(unit):
    mod = registry.get("xrd-process")
    raw = InputFile(name=f"synth_{unit}.txt", data=_ras_text(unit).encode("utf-8"))
    ex = execute(mod, {"raw": [raw]}, {"bg": "none"}, export_figures=False)
    assert ex.previews[0]["spec"]["layout"]["yaxis"]["title"]["text"] == f"Intensity ({unit})"
