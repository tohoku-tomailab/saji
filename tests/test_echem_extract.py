"""echem-extract のテスト（kaiseki-tool の出力との一致 + 解析・指標の単体テスト）。

単体テストは kaiseki-tool の tests/test_echem.py を移植したもの。入力は下の MINI_CP /
MINI_IMP（手で書いた小さな合成データ。値が手計算できるようにしてある）。
"""

from __future__ import annotations

import json
import math
import subprocess
import sys

import numpy as np
import pytest

from saji import registry
from saji.core.runner import execute
from saji.core.tool import InputError, InputFile
from saji.techniques import echem

from .conftest import FIXTURES, GOLDEN, load_input

ECHEM = FIXTURES / "echem"
GOLD = GOLDEN / "echem-extract"

# ============================================================ 小さな合成データ
MINI_CP = """《ファイル情報》
,測定項目情報,0x0506,CP ｸﾛﾉﾎﾟﾃﾝｼｮﾒﾄﾘ
,測定タイトル,

《測定情報》
,面積,2.000000,cm2
,参照電極,Ag/AgCl

《測定フェイズヘッダ》
,フェイズ情報,0x0601,自然電位測定
,サイクル番号,1
,測定点数,2

《測定データ》
,1 時間t,2 電位E,3 電流I,22 自然電位,
,1.000000e+000,-1.000000e-002,0.000000e+000,-1.000000e-002
,2.000000e+000,-2.000000e-002,0.000000e+000,-2.000000e-002

《測定フェイズヘッダ》
,フェイズ情報,0x0600,本測定
,サイクル番号,1
,測定点数,4

《サイクル情報》
,開始時間,2026-02-03 10:00:02
,終了時間,2026-02-03 10:00:06

《測定データ》
,1 時間t,2 電位E,3 電流I,4 WE/CE,種別,
,1.000000e+000,-1.000000e+000,-1.000000e-002,-2.000000e+000,第1電流
,2.000000e+000,-2.000000e+000,-1.000000e-002,-2.100000e+000,第1電流
,3.000000e+000,-3.000000e+000,-2.000000e-002,-2.200000e+000,第2電流
,4.000000e+000,-4.000000e+000,-2.000000e-002,-2.300000e+000,第2電流


《測定フェイズヘッダ》
,フェイズ情報,0x0600,本測定
,サイクル番号,2
,測定点数,2

《測定データ》
,1 時間t,2 電位E,3 電流I,4 WE/CE,種別,
,1.000000e+000,-5.000000e+000,-1.000000e-002,-2.000000e+000,第1電流
,2.000000e+000,-7.000000e+000,-1.000000e-002,-2.100000e+000,第1電流

《解析データヘッダ》
,解析データ数,0
"""

MINI_IMP = """《ファイル情報》
,測定項目情報,0x051C,IMP／定電位 定電位交流ｲﾝﾋﾟｰﾀﾞﾝｽ測定

《測定情報》
,面積,1.000000,cm2

《測定フェイズヘッダ》
,フェイズ情報,0x0600,本測定
,サイクル番号,1

《測定データ》
,1 時間t,2 電位E,3 電流I,4 WE/CE,16 周波数　f,17 Re Z,18 Im Z,
,1.000000e+000,-7.000000e-001,-1.000000e-004,-1.500000e+000,1.000000e+004,3.000000e+000,5.000000e-001
,2.000000e+000,-7.000000e-001,-1.000000e-004,-1.500000e+000,1.000000e+003,4.000000e+000,1.000000e-001
,3.000000e+000,-7.000000e-001,-1.000000e-004,-1.500000e+000,1.000000e+002,6.000000e+000,-3.000000e-001
,4.000000e+000,-7.000000e-001,-1.000000e-004,-1.500000e+000,1.000000e+001,2.000000e+001,-5.000000e+000
,5.000000e+000,-7.000000e-001,-1.000000e-004,-1.500000e+000,1.000000e+000,3.000000e+001,2.000000e+000
,6.000000e+000,-7.000000e-001,-1.000000e-004,-1.500000e+000,1.000000e-001,4.000000e+001,-1.000000e+000
"""


def cp932(text: str) -> bytes:
    return text.replace("\n", "\r\n").encode("cp932")


@pytest.fixture
def cp():
    return echem.parse_bytes(cp932(MINI_CP), "mini_cp.CSV")


@pytest.fixture
def imp():
    return echem.parse_bytes(cp932(MINI_IMP), "mini_imp.CSV")


def run_tool(files: list[InputFile], params: dict | None = None):
    return execute(registry.get("echem-extract"), {"raw": files}, params or {},
                   export_figures=False)


# ============================================================ ゴールデン（kaiseki-tool と一致）
#: tests/golden/echem-extract/from_kaiseki.py の CASES と対応（kaiseki の引数 → saji のパラメータ）
CASES: dict[str, tuple[list[str], dict]] = {
    "cp_default": (["cp_synth.CSV"], {}),
    "imp_default": (["imp_synth.CSV"], {}),
    "unknown_default": (["unknown_synth.CSV"], {}),
    "cp_all_rename": (["cp_synth.CSV"], {"phase": "all", "rename": True, "avg_range": "60,"}),
    "cp_cycle2_all": (["cp_synth.CSV"], {"cycle": 2, "metrics": "all"}),
    "cp_cp932": (["cp_synth.CSV"], {"encoding": "cp932", "avg_range": ",30"}),
    "imp_interp_last": (["imp_synth.CSV"], {"rs_method": "interp", "rs_crossing": "last"}),
    "imp_rest": (["imp_synth.CSV"], {"phase": "0x0601"}),
    "imp_crossing2": (["imp_synth.CSV"], {"rs_crossing": "-2", "metrics": "resistance", "data": False}),
    "batch": (["cp_synth.CSV", "imp_synth.CSV", "unknown_synth.CSV"], {}),
}


def assert_close(actual, expected, where=""):
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and list(actual) == list(expected), where
        for k in expected:
            assert_close(actual[k], expected[k], f"{where}.{k}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), where
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert_close(a, e, f"{where}[{i}]")
    elif isinstance(expected, float):
        assert actual == pytest.approx(expected, rel=1e-12, abs=0), where
    else:
        assert actual == expected, where


@pytest.mark.parametrize("case", sorted(CASES))
def test_matches_golden(case):
    names, params = CASES[case]
    ex = run_tool([load_input(ECHEM / n) for n in names], params)
    files = {f.path: f.data for f in ex.files}
    gold = {p.name: p.read_bytes() for p in (GOLD / case).iterdir()}
    for name, expected in gold.items():
        assert name in files, f"{name} が出力されていません（出力: {sorted(files)}）"
        assert files[name] == expected, name
    # saji は常に echem_metrics.csv / .json を出す（kaiseki は一括時だけ CSV を出していた）
    extra = set(files) - set(gold) - {"manifest.json"}
    assert extra <= {"echem_metrics.csv", "echem_metrics.json"}
    assert "echem_metrics.csv" in files and "echem_metrics.json" in files
    if "echem_metrics.json" in gold:
        expected = json.loads(gold["echem_metrics.json"])
        assert_close(ex.result.data["metrics"], expected)
        assert all("path" not in r for r in ex.result.data["metrics"])


def test_golden_metrics_values():
    """ゴールデンの中身が意図どおり（合成データの等価回路から期待される値）か。"""
    ex = run_tool([load_input(ECHEM / "imp_synth.CSV")])
    rec = ex.result.data["metrics"][0]
    assert rec["kind"] == "IMP"
    assert rec["solution_resistance_ohm"] == pytest.approx(12.3, abs=0.05)   # Rs = 12.3 Ω
    assert rec["n_crossings"] > 1 and rec["crossing_index"] == 0
    assert 1e4 < rec["crossing_freq_after_hz"] < rec["crossing_freq_before_hz"] < 3e4
    assert any("符号反転" in w for w in ex.result.warnings)


# ============================================================ run() の振る舞い
def test_no_matching_phase_is_input_error():
    with pytest.raises(InputError, match="該当フェイズがありません"):
        run_tool([load_input(ECHEM / "cp_synth.CSV")], {"phase": "0x9999"})


def test_partial_failure_warns_and_continues():
    rest_only = cp932(MINI_CP.split("《測定フェイズヘッダ》\n,フェイズ情報,0x0600")[0])
    ex = run_tool([InputFile("rest_only.CSV", rest_only), load_input(ECHEM / "unknown_synth.CSV")])
    assert [s["file"] for s in ex.result.data["skipped"]] == ["rest_only.CSV"]
    assert "自然電位測定" in ex.result.data["skipped"][0]["reason"]
    assert any("rest_only.CSV" in w for w in ex.result.warnings)
    assert [r["file"] for r in ex.result.data["metrics"]] == ["unknown_synth.CSV"]


def test_bad_params_are_input_errors():
    f = [load_input(ECHEM / "cp_synth.CSV")]
    with pytest.raises(InputError, match="rs_crossing"):
        run_tool(f, {"rs_crossing": "middle"})
    with pytest.raises(InputError, match="encoding"):
        run_tool(f, {"encoding": "no-such-codec"})
    with pytest.raises(InputError, match="文字コード"):
        run_tool(f, {"encoding": "ascii"})              # 列名の日本語を書けない


def test_metrics_none_and_no_data():
    ex = run_tool([load_input(ECHEM / "cp_synth.CSV")], {"metrics": "none"})
    names = [f.path for f in ex.files]
    assert names == ["cp_synth_main_cycle1.csv", "cp_synth_main_cycle2.csv", "manifest.json"]
    assert ex.result.data["metrics"] == []
    ex = run_tool([load_input(ECHEM / "cp_synth.CSV")], {"data": False})
    assert [f.path for f in ex.files] == ["echem_metrics.csv", "echem_metrics.json", "manifest.json"]


def test_duplicate_names_are_skipped():
    f = load_input(ECHEM / "unknown_synth.CSV")
    ex = run_tool([f, InputFile("UNKNOWN_SYNTH.csv", f.data)])
    assert len(ex.result.data["metrics"]) == 1
    assert ex.result.data["skipped"][0]["file"] == "UNKNOWN_SYNTH.csv"


def test_duplicate_phase_tag_gets_suffix():
    """同じコード・同じサイクルの本測定が2つあっても上書きしない。"""
    text = MINI_CP.replace(",サイクル番号,2", ",サイクル番号,1")
    ex = run_tool([InputFile("dup.CSV", cp932(text))])
    names = [f.path for f in ex.files]
    assert "dup_main_cycle1.csv" in names and "dup_main_cycle1_1.csv" in names
    assert any("重なる" in w for w in ex.result.warnings)


def test_preview_figures():
    ex = run_tool([load_input(ECHEM / n) for n in ("cp_synth.CSV", "imp_synth.CSV")])
    prev = {p["name"]: p["spec"] for p in ex.previews}
    assert set(prev) == {"cp_synth_preview", "imp_synth_preview"}
    cp_fig, imp_fig = prev["cp_synth_preview"], prev["imp_synth_preview"]
    assert [t["name"] for t in cp_fig["data"]] == ["main_cycle1", "main_cycle2"]
    assert cp_fig["layout"]["yaxis"]["title"]["text"] == "Potential (V)"
    assert imp_fig["layout"]["xaxis"]["title"]["text"] == "Z' (Ω)"
    rs = ex.result.data["metrics"][2]["solution_resistance_ohm"]
    assert imp_fig["layout"]["shapes"][0]["x0"] == pytest.approx(rs)
    # プレビュー専用なので成果物の図は出ない
    assert not any(f.path.endswith((".png", ".svg")) for f in ex.files)
    assert not any("Arial" in w for w in ex.result.warnings)


# ============================================================ parse（kaiseki から移植）
def test_parse_cp_file_info_and_phases(cp):
    assert cp.item_code == "0x0506"
    assert cp.item_name.startswith("CP")
    assert cp.info_float("面積") == 2.0
    assert cp.info_value("参照電極") == "Ag/AgCl"
    assert [p.code for p in cp.phases] == ["0x0601", "0x0600", "0x0600"]
    assert [p.cycle for p in cp.phases] == [1, 1, 2]
    assert len(cp.main_phases()) == 2


def test_parse_main_phase_table(cp):
    main = cp.main_phases()[0]
    assert list(main.df.columns) == ["1 時間t", "2 電位E", "3 電流I", "4 WE/CE", "種別"]
    assert len(main.df) == 4                       # 末尾の空列・空行は落ちる
    assert main.df["2 電位E"].tolist() == [-1.0, -2.0, -3.0, -4.0]
    assert main.df["種別"].tolist() == ["第1電流"] * 2 + ["第2電流"] * 2
    assert main.start_time == "2026-02-03 10:00:02"
    assert main.n_points == 4


def test_parse_phase_without_cycle_info(cp):
    """《サイクル情報》が無いフェイズでも落ちない（時刻は None）。"""
    second = cp.main_phases()[1]
    assert second.cycle == 2 and second.start_time is None
    assert second.df["2 電位E"].tolist() == [-5.0, -7.0]


def test_select_phases(cp):
    assert len(cp.select_phases()) == 2                       # 既定=本測定
    assert len(cp.select_phases("all")) == 3
    assert len(cp.select_phases(cycle=2)) == 1
    assert cp.select_phases("0x0601")[0].name == "自然電位測定"
    assert cp.select_phases("自然電位")[0].code == "0x0601"    # 名前の部分一致
    assert cp.select_phases("0x9999") == []


def test_parse_encoding_independent():
    """cp932 でも BOM 付き UTF-8 でも同じ結果になる。"""
    ef = echem.parse_bytes(MINI_CP.encode("utf-8-sig"), "u.CSV")
    assert ef.main_phases()[0].df["2 電位E"].tolist() == [-1.0, -2.0, -3.0, -4.0]


def test_strip_item_number():
    assert echem.strip_item_number("17 Re Z") == "Re Z"
    assert echem.strip_item_number("1 時間t") == "時間t"
    assert echem.strip_item_number("種別") == "種別"


def test_phase_csv_rename(cp):
    head = echem.phase_csv(cp.main_phases()[0], rename=True).decode("utf-8-sig").splitlines()[0]
    assert head == "time_s,E_V,I_A,WE_CE_V,kind"


# ============================================================ 列解決・測定種
def test_resolve_data_columns(imp):
    cols = echem.resolve_data_columns(imp.main_phases()[0].df)
    assert cols["time"] == 0 and cols["potential"] == 1
    assert cols["freq"] == 4 and cols["re_z"] == 5 and cols["im_z"] == 6   # 全角空白入りの列名
    assert "kind" not in cols


def test_detect_kind(cp, imp):
    assert echem.detect_kind(cp) == echem.KIND_CP
    assert echem.detect_kind(imp) == echem.KIND_IMP


def test_detect_kind_from_columns_when_code_unknown(imp):
    imp.item_code = "0x0999"
    assert echem.detect_kind(imp) == echem.KIND_IMP


# ============================================================ 平均電位
def test_average_potential_whole_phase(cp):
    stats = echem.average_potential(cp.main_phases()[0].df)
    assert stats.mean == pytest.approx(-2.5)
    assert stats.n == 4
    assert stats.min == -4.0 and stats.max == -1.0
    assert stats.by_kind == {"第1電流": pytest.approx(-1.5), "第2電流": pytest.approx(-3.5)}


def test_average_potential_time_range(cp):
    df = cp.main_phases()[0].df
    assert echem.average_potential(df, time_range=(3, None)).mean == pytest.approx(-3.5)
    assert echem.average_potential(df, time_range=(None, 2)).mean == pytest.approx(-1.5)
    assert echem.average_potential(df, time_range=(2, 3)).n == 2


def test_average_potential_errors(cp):
    df = cp.main_phases()[0].df
    with pytest.raises(ValueError):
        echem.average_potential(df, time_range=(100, 200))       # 範囲にデータなし
    with pytest.raises(ValueError):
        echem.average_potential(df.drop(columns=["2 電位E"]))      # 電位の列が無い


# ============================================================ 溶液抵抗
def test_find_im_z_crossings():
    im = np.array([0.5, 0.1, -0.3, -5.0, 2.0, -1.0])
    assert echem.find_im_z_crossings(im) == [(1, 2), (3, 4), (4, 5)]
    im = np.array([0.5, math.nan, -0.3, 0.0, 0.0, 1.0])            # NaN は飛ばす・0→0 は数えない
    assert echem.find_im_z_crossings(im) == [(0, 2), (2, 3), (4, 5)]


def test_solution_resistance_first_crossing(imp):
    res = echem.solution_resistance(imp.main_phases()[0].df)
    assert res.resistance == pytest.approx(5.0)        # (4 + 6) / 2
    assert res.n_crossings == 3 and res.crossing_index == 0
    assert res.freq_before == 1000.0 and res.freq_after == 100.0


def test_solution_resistance_interp_and_selection(imp):
    df = imp.main_phases()[0].df
    # Im Z = 0 への内挿: 4 + (6-4) * (0-0.1)/(-0.3-0.1) = 4.5
    assert echem.solution_resistance(df, method="interp").resistance == pytest.approx(4.5)
    assert echem.solution_resistance(df, crossing="last").resistance == pytest.approx(35.0)
    assert echem.solution_resistance(df, crossing=1).resistance == pytest.approx(25.0)
    assert echem.solution_resistance(df, crossing=-1).crossing_index == 2
    with pytest.raises(ValueError):
        echem.solution_resistance(df, crossing=9)
    with pytest.raises(ValueError):
        echem.solution_resistance(df, method="unknown")


def test_solution_resistance_without_impedance_columns(cp):
    with pytest.raises(ValueError):
        echem.solution_resistance(cp.main_phases()[0].df)


# ============================================================ まとめ
def test_summarize_phase_auto(imp):
    rec = echem.summarize_phase(imp, imp.main_phases()[0])
    assert rec["kind"] == echem.KIND_IMP and rec["cycle"] == 1
    assert rec["solution_resistance_ohm"] == pytest.approx(5.0)
    assert rec["average_potential_V"] == pytest.approx(-0.7)
    assert rec["area_cm2"] == 1.0
    assert "path" not in rec and rec["file"] == "mini_imp.CSV"


def test_summarize_phase_records_error_without_stopping(cp):
    """算出できない指標は *_error に理由が入るだけで、処理は止まらない。"""
    rec = echem.summarize_phase(cp, cp.main_phases()[0], metrics="all")
    assert rec["average_potential_V"] == pytest.approx(-2.5)
    assert "resistance_error" in rec


def test_flatten_metrics():
    flat = echem.flatten_metrics({"a": 1, "r": [60.0, None], "k": {"x": 1.5}})
    assert flat == {"a": 1, "r": "60.0,", "k[x]": 1.5}


# ============================================================ CLI
def run_cli(*args: str, tmp_path):
    return subprocess.run([sys.executable, "-m", "saji.cli", "echem-extract", *args,
                           "--output-dir", str(tmp_path), "--json"],
                          capture_output=True, text=True, encoding="utf-8")


def test_cli_ok(tmp_path):
    proc = run_cli(str(ECHEM / "imp_synth.CSV"), "--no-data", tmp_path=tmp_path)
    assert proc.returncode == 0, proc.stderr
    summary = json.loads(proc.stdout)
    assert summary["ok"] and summary["data"]["metrics"][0]["kind"] == "IMP"
    assert sorted(summary["files"]) == ["echem_metrics.csv", "echem_metrics.json", "manifest.json"]


def test_cli_bad_input_exit_2(tmp_path):
    proc = run_cli(str(ECHEM / "cp_synth.CSV"), "--phase", "0x9999", tmp_path=tmp_path)
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["ok"] is False
