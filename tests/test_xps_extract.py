"""xps-extract のゴールデンテスト（kaiseki-tool の出力と一致すること）と、.spe 解析の単体テスト。"""

from __future__ import annotations

import struct

import pytest

from saji import registry
from saji.core.runner import execute
from saji.core.tool import InputError, InputFile
from saji.techniques.xps import extract as ex
from saji.techniques.xps.spe import is_spe, parse_regions, parse_spe

from .conftest import FIXTURES, GOLDEN, load_input

XPS = FIXTURES / "xps"
SPE = "20260101_Synth.1.sampleA.spe"
TXT = "20260101_Synth.2.sampleB.txt"
TXT2 = "20260101_Synth.3.sampleC.txt"

# ケース名: (入力, パラメータ, 期待される出力ファイル)。ゴールデンは kaiseki xps extract の出力
CASES = {
    "spe_all": (SPE, {}, ["sampleA_Su1s.csv", "sampleA_C1s.csv", "sampleA_O1s.csv", "sampleA_CuLMM.csv"]),
    "spe_shift": (SPE, {"labels": "C1s,Cu LMM", "energy_shift": 1.0906, "normalize": False},
                  ["sampleA_C1s.csv", "sampleA_CuLMM.csv"]),
    "txt_default": (TXT, {}, ["sampleB_Survey.csv"]),
    "txt_labels": (TXT, {"labels": "Survey,C1s,O1s,Cu_LMM,N1s", "energy_shift": -0.4838,
                         "normalize": False},
                   ["sampleB_Survey.csv", "sampleB_C1s.csv", "sampleB_O1s.csv"]),
    "txt_offset2": (TXT2, {"labels": "C1s,O1s", "offset": 2}, ["sampleC_C1s.csv", "sampleC_O1s.csv"]),
}


def _run(files, params):
    mod = registry.get("xps-extract")
    return execute(mod, {"raw": [load_input(XPS / f) for f in files]}, params, export_figures=False)


@pytest.mark.parametrize("case", sorted(CASES))
def test_matches_golden(case):
    src, params, expected = CASES[case]
    exe = _run([src], params)
    files = {f.path: f.data for f in exe.files if f.path != "manifest.json"}
    assert list(files) == expected
    for name in expected:
        assert files[name] == (GOLDEN / "xps-extract" / f"{case}-{name}").read_bytes(), name


def test_missing_labels_warn_and_data():
    exe = _run([TXT], CASES["txt_labels"][1])
    # テキストのラベルは完全一致（Cu_LMM では Cu LMM に当たらない。kaiseki-tool と同じ）
    assert exe.result.warnings == [
        f"ラベル 'Cu_LMM' のデータが見つかりません: {TXT}",
        f"ラベル 'N1s' のデータが見つかりません: {TXT}",
    ]
    info = exe.result.data["files"][0]
    assert info["sample"] == "sampleB"
    assert info["missing_labels"] == ["Cu_LMM", "N1s"]
    assert [r["n_points"] for r in info["regions"]] == [1101, 161, 121]


def test_spe_and_txt_together_no_warnings():
    exe = _run([SPE, TXT], {})
    names = [f.path for f in exe.files if f.path != "manifest.json"]
    assert names == ["sampleA_Su1s.csv", "sampleA_C1s.csv", "sampleA_O1s.csv",
                     "sampleA_CuLMM.csv", "sampleB_Survey.csv"]
    assert not exe.result.warnings


def test_duplicate_output_name_warns_and_keeps_last():
    a = load_input(XPS / TXT)
    b = InputFile("20260102_Other.9.sampleB.txt", a.data)
    exe = execute(registry.get("xps-extract"), {"raw": [a, b]}, {}, export_figures=False)
    assert [f.path for f in exe.files].count("sampleB_Survey.csv") == 1
    assert any("重複" in w for w in exe.result.warnings)


def test_broken_spe_is_input_error():
    with pytest.raises(InputError, match="EOFH"):
        execute(registry.get("xps-extract"), {"raw": [InputFile("x.spe", b"not a spe file")]}, {})


# ============================================================ 単体テスト（kaiseki-tool の tests/test_xps*.py から移植）
MULTIPAK = (
    "SOFH\nInstrumentModel: PHI5000\nDate: 2026/01/01\nSOFE\n"
    "Survey\n1\nBinding Energy (eV)\nIntensity (counts)\n5\n"
    "1400.0,100.0\n1399.0,300.0\n1398.0,150.0\n1397.0,500.0\n1396.0,100.0\n\n"
    "Cu2p3\n1\nBinding Energy (eV)\nIntensity (counts)\n3\n"
    "938.0,10.0\n936.0,30.0\n934.0,20.0\n\nEOF\n"
).encode("ascii")
MULTIPAK_NAME = "20260101_Test.1.sampleA.txt"


def build_spe(regions):
    """(名前, 開始BE, 終了BE, [y...]) の一覧から最小限の .spe バイト列を組み立てる。"""
    header = ["SOFH", "FileType:  SPECTRUM", f"NoSpectralReg: {len(regions)}"]
    for i, (name, x0, x1, ys) in enumerate(regions, start=1):
        header.append(f"SpectralRegDef: {i} 1 {name} 29 {len(ys)} -0.1000 "
                      f"{x0:.4f} {x1:.4f} {x0 - 1:.4f} {x1 + 1:.4f} 1.200000 23.50 AREA")
        header.append(f"SpectralRegDefFull: {i} 0 Dummy{i} 1 3 -1.0 10.0 0.0 10.0 0.0 0.0 1.0 AREA")
    header.append("EOFH")
    head = ("\r\n".join(header) + "\r\n").encode("latin-1")
    data_start = (4 + 24 * len(regions)) * 4
    table = [1, len(regions), 768, 16]
    blobs, offset = [], data_start
    for _name, _x0, _x1, ys in regions:
        entry = [0] * 24
        entry[5], entry[19], entry[20] = len(ys), len(ys) * 4, offset
        table += entry
        blobs.append(struct.pack(f"<{len(ys)}f", *ys))
        offset += len(ys) * 4
    return head + struct.pack(f"<{len(table)}i", *table) + b"".join(blobs)


REGIONS = [("C1s", 298.0, 296.0, [10.0, 20.0, 30.0, 20.0, 10.0]),
           ("Cu_LMM", 580.0, 578.0, [1.0, 2.0, 3.0])]
SPE_BYTES = build_spe(REGIONS)
SPE_NAME = "20260903-Name.120.rc9.spe"


def test_extract_file_survey_normalized():
    rows = ex.extract_file(MULTIPAK_NAME, MULTIPAK, labels=["Survey"])["Survey"]
    assert len(rows) == 5
    ys = [y for _, y in rows]
    assert min(ys) == 0.0 and max(ys) == 1.0
    assert rows[0][0] == 1400.0          # x はそのまま（正規化は y のみ）


def test_extract_file_multiple_labels_and_missing():
    spectra = ex.extract_file(MULTIPAK_NAME, MULTIPAK, labels=["Survey", "Cu2p3", "O1s"],
                              normalize=False)
    assert set(spectra) == {"Survey", "Cu2p3"}
    assert spectra["Cu2p3"] == [(938.0, 10.0), (936.0, 30.0), (934.0, 20.0)]


def test_normalize_minmax_flat_is_zero():
    assert ex.normalize_minmax([(1.0, 5.0), (2.0, 5.0)]) == [(1.0, 0.0), (2.0, 0.0)]


def test_infer_sample_name():
    assert ex.infer_sample_name("20260713_Name.108.reCupH7fA.txt") == "reCupH7fA"
    assert ex.infer_sample_name(MULTIPAK_NAME) == "sampleA"


def test_is_spe():
    assert is_spe("x.spe") and is_spe("X.SPE")
    assert not is_spe("x.txt") and not is_spe("x.csv")


def test_parse_regions_ignores_full_definitions():
    header = SPE_BYTES.split(b"EOFH")[0].decode("latin-1")
    assert parse_regions(header) == [("C1s", 5, 298.0, 296.0), ("Cu_LMM", 3, 580.0, 578.0)]


def test_parse_spe_values_and_axis():
    spectra = parse_spe(SPE_BYTES)
    assert list(spectra) == ["C1s", "Cu_LMM"]
    assert spectra["C1s"] == [(298.0, 10.0), (297.5, 20.0), (297.0, 30.0), (296.5, 20.0), (296.0, 10.0)]
    assert spectra["Cu_LMM"] == [(580.0, 1.0), (579.0, 2.0), (578.0, 3.0)]


def test_parse_spe_rejects_inconsistent_table():
    broken = bytearray(SPE_BYTES)
    body = broken.index(b"EOFH") + 6
    struct.pack_into("<i", broken, body + (4 + 5) * 4, 99)     # 1領域目の点数を壊す
    with pytest.raises(ValueError, match="矛盾"):
        parse_spe(bytes(broken))


def test_extract_file_spe_defaults_and_label_filter():
    assert list(ex.extract_file(SPE_NAME, SPE_BYTES, normalize=False)) == ["C1s", "Cu_LMM"]
    # Multipak は "Cu LMM"、.spe は "Cu_LMM" と書くのでどちらでも当たること
    assert list(ex.extract_file(SPE_NAME, SPE_BYTES, labels=["Cu LMM"])) == ["Cu_LMM"]


def test_energy_shift_moves_x_only():
    rows = ex.extract_file(SPE_NAME, SPE_BYTES, labels=["C1s"], normalize=False,
                           energy_shift=0.4838)["C1s"]
    assert [x for x, _ in rows] == [298.4838, 297.9838, 297.4838, 296.9838, 296.4838]
    assert [y for _, y in rows] == [10.0, 20.0, 30.0, 20.0, 10.0]


def test_tool_spe_writes_all_regions():
    exe = execute(registry.get("xps-extract"), {"raw": [InputFile(SPE_NAME, SPE_BYTES)]},
                  {"energy_shift": 1.0}, export_figures=False)
    files = {f.path: f.data for f in exe.files}
    assert sorted(n for n in files if n.endswith(".csv")) == ["rc9_C1s.csv", "rc9_CuLMM.csv"]
    body = files["rc9_C1s.csv"].decode("utf-8").splitlines()
    assert body[0] == "x,y"
    assert body[1] == "299.0,0.0"          # x はシフト済み、y は 0-1 正規化


def test_squash_label():
    assert ex.squash_label("Cu LMM") == ex.squash_label("Cu_LMM") == "CuLMM"
