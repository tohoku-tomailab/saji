"""mpt-cycle のテスト（CSV が移植元 mpt-cycle-extractor-webui の出力とバイト単位で一致すること・図）。

ゴールデン（tests/golden/mpt-cycle/）は、移植元の index.html の抽出関数を Node で実行して作った
（tests/golden/mpt-cycle/from_webui.mjs。条件は cases.json、saji のパラメータとの対応は下の CASES）。
"""

from __future__ import annotations

import importlib
import json
import math
import os

import pytest

from saji.core.plot.checks import non_arial_texts
from saji.core.runner import execute
from saji.core.tool import InputError, InputFile
from saji.techniques import eclab

from .conftest import FIXTURES, GOLDEN, load_input

MOD = importlib.import_module("saji.tools.mpt_cycle")
DIR = FIXTURES / "eclab"
GOLD = GOLDEN / "mpt-cycle"
WEBUI = json.loads((GOLD / "cases.json").read_text(encoding="utf-8"))

# ケース名（cases.json と同じ）→ saji のパラメータ
CASES = {
    "utf8-rhe": {"ph": 14},
    "utf8-norhe-cycle1": {"cycle": 1, "rhe": False},
    "utf8-rhe-custom": {"cycle": 3, "ph": 7.4, "reference": "custom", "ref_potential": 0.2},
    "comma-rhe": {"ph": 13, "reference": "ag-agcl-sat-kcl", "temperature": 30},
    "comma-missing-cycle": {"cycle": 5, "ph": 13, "reference": "ag-agcl-sat-kcl"},
    "not-eclab": {"ph": 13, "reference": "ag-agcl-sat-kcl"},
}

# 図のスナップショット（tests/golden/figures/mpt-cycle-<名前>.json）
FIGURE_CASES = {
    "overlay": (["cv_utf8.mpt", "cv_utf8_b.mpt"], {"ph": 14}),
    "single-norhe": (["cv_utf8.mpt"], {"rhe": False, "title": "Cycle 2", "xlim": "0,0.8"}),
}


def run_files(names: list[str], params: dict, **kw):
    return execute(MOD, {"mpt": [load_input(DIR / n) for n in names]}, params,
                   export_figures=False, **kw)


def test_cases_cover_webui_cases():
    assert set(CASES) == set(WEBUI)


# ============================================================ ゴールデン
@pytest.mark.parametrize("case", sorted(c for c in CASES if "output" in WEBUI[c]))
def test_csv_matches_webui(case):
    exp = WEBUI[case]
    ex = run_files([exp["file"]], CASES[case])
    files = {f.path: f.data for f in ex.files}
    assert files[exp["output"]] == (GOLD / case / exp["output"]).read_bytes()
    assert ex.result.data["files"] == [{"source": exp["file"], "output": exp["output"], "rows": exp["rows"]}]
    assert not ex.result.warnings


@pytest.mark.parametrize("case", sorted(c for c in CASES if "error" in WEBUI[c]))
def test_error_cases_are_skipped(case):
    """移植元でエラーになるファイルは、警告して飛ばす（1つも処理できなければ InputError）。"""
    exp = WEBUI[case]
    with pytest.raises(InputError, match="処理できたファイルがありません"):
        run_files([exp["file"]], CASES[case])


def test_bad_file_is_skipped_with_warning():
    ex = run_files(["cv_utf8.mpt", "not_eclab.mpt"], {"ph": 13})
    assert [f["source"] for f in ex.result.data["files"]] == ["cv_utf8.mpt"]
    assert ex.result.data["failed"] == ["not_eclab.mpt"]
    assert len(ex.result.warnings) == 1
    assert "not_eclab.mpt" in ex.result.warnings[0] and "EC-Lab ASCII" in ex.result.warnings[0]


def test_missing_cycle_lists_available():
    ex = run_files(["cv_utf8.mpt", "cv_comma.mpt"], {"cycle": 3, "ph": 13})
    assert ex.result.data["failed"] == ["cv_comma.mpt"]
    assert "サイクル 3 がありません（存在: 1, 2）" in ex.result.warnings[0]


def test_format_g10_matches_webui():
    for value, expected in json.loads((GOLD / "format_g10.json").read_text(encoding="utf-8")):
        assert eclab.format_g10(value) == expected, value


# ============================================================ 細かい挙動
def test_rhe_formula():
    slope = eclab.ph_slope(25)
    assert slope == pytest.approx(0.0591593, abs=1e-7)
    ex = run_files(["cv_utf8.mpt"], {"ph": 14})
    rhe = ex.result.data["rhe"]
    assert rhe["ref_vs_she"] == 0.105
    assert rhe["offset"] == pytest.approx(0.105 + slope * 14)


def test_fractional_cycle_and_cycle_column():
    text = ("EC-Lab ASCII FILE\nNb header lines : 4\n\nEwe/V\tI/mA\tcycle\t\n"
            "0,1\t1\t1,5\t\n0,2\t2\t1,5\t\n0,3\t3\t2\t\n")
    ex = execute(MOD, {"mpt": [InputFile("x.y.mpt", text.encode())]}, {"cycle": 1.5, "rhe": False},
                 export_figures=False)
    assert [f.path for f in ex.files if f.path.endswith(".csv")] == ["x.y_cycle1p5.csv"]
    assert ex.files[0].data == ('\ufeff"Ewe/V","I/mA","cycle"\r\n"0,1","1","1,5"\r\n'
                                '"0,2","2","1,5"\r\n').encode("utf-8")
    assert ex.previews[0]["name"] == "x.y_cycle1p5"
    assert ex.previews[0]["spec"]["data"][0]["x"] == [0.1, 0.2]


def test_param_errors():
    with pytest.raises(InputError, match="ph を指定"):
        run_files(["cv_utf8.mpt"], {})
    with pytest.raises(InputError, match="ref_potential"):
        run_files(["cv_utf8.mpt"], {"ph": 7, "reference": "custom"})
    with pytest.raises(InputError, match="14.5 以下"):
        run_files(["cv_utf8.mpt"], {"ph": 15})
    with pytest.raises(InputError, match="絶対零度"):
        run_files(["cv_utf8.mpt"], {"ph": 7, "temperature": -300})
    with pytest.raises(InputError, match="列 'nope' がどのファイルにもありません"):
        run_files(["cv_utf8.mpt"], {"ph": 7, "y": "nope"})


def test_ref_potential_overrides_preset():
    ex = run_files(["cv_utf8.mpt"], {"ph": 7, "ref_potential": 0.1})
    assert ex.result.data["rhe"]["ref_vs_she"] == 0.1
    assert any("ref_potential=0.1" in m for m in ex.result.logs)


def test_default_columns_and_labels():
    ex = run_files(["cv_utf8.mpt", "cv_utf8_b.mpt"], {"ph": 14})
    assert ex.result.data["plot"] == {"series": [
        {"label": "cv_utf8", "x": "E_RHE/V", "y": "<I>/mA"},
        {"label": "cv_utf8_b", "x": "E_RHE/V", "y": "<I>/mA"}]}
    spec = ex.previews[0]["spec"]
    assert ex.previews[0]["name"] == "CV_cycle2_RHE_overlay"
    assert spec["layout"]["xaxis"]["title"]["text"] == "E / V vs. RHE"
    assert spec["layout"]["yaxis"]["title"]["text"] == "I / mA"
    assert not ex.result.warnings


def test_default_columns_per_file():
    """列の既定はファイルごとに候補の順で選ぶ（<I>/mA のファイルと I/mA のファイルを重ねられる）。"""
    ex = run_files(["cv_utf8.mpt", "cv_comma.mpt"], {"rhe": False})
    assert ex.result.data["plot"] == {"series": [
        {"label": "cv_utf8", "x": "Ewe/V", "y": "<I>/mA"},
        {"label": "cv_comma", "x": "<Ewe>/V", "y": "I/mA"}]}
    spec = ex.previews[0]["spec"]
    assert [spec["layout"][k]["title"]["text"] for k in ("xaxis", "yaxis")] == ["E / V", "I / mA"]
    assert not ex.result.warnings


def test_mixed_units_warn():
    text = ("EC-Lab ASCII FILE\nNb header lines : 3\nEwe/V\tI/A\tcycle number\n"
            "0.1\t0.001\t2\n0.2\t0.002\t2\n")
    ex = execute(MOD, {"mpt": [load_input(DIR / "cv_utf8.mpt"), InputFile("amp.mpt", text.encode())]},
                 {"rhe": False}, export_figures=False)
    assert [s["y"] for s in ex.result.data["plot"]["series"]] == ["<I>/mA", "I/A"]
    assert any("y 軸の列がファイルによって違います" in w for w in ex.result.warnings)
    ex = execute(MOD, {"mpt": [load_input(DIR / "cv_utf8.mpt"), InputFile("amp.mpt", text.encode())]},
                 {"rhe": False, "y": "I/A"}, export_figures=False)
    assert [s["label"] for s in ex.result.data["plot"]["series"]] == ["amp"]
    assert any("cv_utf8.mpt は図に描きませんでした" in w for w in ex.result.warnings)


def test_measurement_order_is_kept():
    """CV の往復を保つため、x で並べ替えない。"""
    ex = run_files(["cv_utf8.mpt"], {"rhe": False})
    x = ex.previews[0]["spec"]["data"][0]["x"]
    top = x.index(max(x))
    assert 0 < top < len(x) - 1
    assert x[:top + 1] == sorted(x[:top + 1]) and x[top:] == sorted(x[top:], reverse=True)


def test_traces_select_order_label_color():
    traces = [{"file": "cv_comma.mpt", "label": "B", "color": "#ff0000"}, {"file": "C:\\data\\cv_utf8.mpt"},
              {"file": "missing.mpt"}]
    ex = run_files(["cv_utf8.mpt", "cv_comma.mpt"], {"ph": 14, "y": "I/mA", "traces": traces})
    data = ex.previews[0]["spec"]["data"]
    # cv_utf8 には I/mA が無い（<I>/mA）ので描かれない
    assert [(t["name"], t["line"]["color"]) for t in data] == [("B", "#ff0000")]
    assert any("cv_utf8.mpt は図に描きませんでした" in w for w in ex.result.warnings)
    assert any("missing.mpt" in w for w in ex.result.warnings)
    ex = run_files(["cv_utf8.mpt", "cv_comma.mpt"], {"rhe": False, "y": "<I>/mA", "traces": [{"file": "cv_utf8.mpt"}]})
    assert [t["name"] for t in ex.previews[0]["spec"]["data"]] == ["cv_utf8"]
    assert [f.path for f in ex.files if f.path.endswith(".csv")] == ["cv_utf8_cycle2.csv", "cv_comma_cycle2.csv"]
    assert any("図に描かなかった" in m and "cv_comma.mpt" in m for m in ex.result.logs)


def test_axis_label():
    assert eclab.axis_label("<Ewe>/V") == "E / V"
    assert eclab.axis_label("I/µA") == "I / µA"
    assert eclab.axis_label("(Q-Qo)/C") == "(Q-Qo) / C"
    assert eclab.axis_label("cycle number") == "cycle number"


def test_parse_loose():
    assert eclab.parse_loose(" 1,5 ") == 1.5
    assert eclab.parse_loose("2.000000000000000E+000") == 2.0
    assert math.isnan(eclab.parse_loose(""))
    assert math.isnan(eclab.parse_loose("abc"))
    assert math.isnan(eclab.parse_loose("1_0"))


def test_decode_order():
    assert eclab.decode("\ufeffEC-Lab ASCII FILE ±".encode("utf-8")) == "EC-Lab ASCII FILE ±"
    # UTF-8 として読めなければ Shift_JIS（移植元と同じ。CP1252 の ° は半角カナになる）
    assert eclab.decode("25 °C".encode("cp1252")) == "25 ｰC"


# ============================================================ 図
@pytest.mark.parametrize("name", sorted(FIGURE_CASES))
def test_figure_snapshot(name):
    """図の JSON のスナップショット（意図して図を変えたときだけ SAJI_UPDATE_SNAPSHOTS=1 で作り直す）。"""
    files, params = FIGURE_CASES[name]
    ex = run_files(files, params)
    spec = json.loads(json.dumps(ex.previews[0]["spec"], ensure_ascii=False, allow_nan=False))
    assert not non_arial_texts(spec)
    path = GOLDEN / "figures" / f"mpt-cycle-{name}.json"
    if os.environ.get("SAJI_UPDATE_SNAPSHOTS"):
        path.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    assert spec == json.loads(path.read_text(encoding="utf-8"))
