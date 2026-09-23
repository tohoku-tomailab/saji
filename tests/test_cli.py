"""CLI（--json の形式・終了コード・--dry-run・--params）のテスト。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from saji.cli import main

from .conftest import FIXTURES

TXT = str(FIXTURES / "xrd" / "synthA.TXT")


def run_cli(capsys, *args):
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


def test_list(capsys):
    code, out, _ = run_cli(capsys, "list", "--json")
    assert code == 0
    names = [t["name"] for t in json.loads(out)]
    assert "xrd-process" in names


def test_help_shows_units_and_defaults(capsys):
    with pytest.raises(SystemExit) as e:
        main(["xrd-process", "--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "--norm-ref-pos" in out and "単位 deg" in out and "既定" in out


def test_run_json_summary(capsys, tmp_path):
    code, out, err = run_cli(capsys, "xrd-process", TXT, "--norm", "max",
                             "--output-dir", str(tmp_path), "--json")
    assert code == 0
    summary = json.loads(out)          # 標準出力は JSON だけ
    assert summary["ok"] is True and summary["tool"] == "xrd-process"
    out_dir = Path(summary["output_dir"])
    assert out_dir.parent == tmp_path and out_dir.name.endswith("-xrd-process")
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "synthA_processed.xy").exists()
    assert (out_dir / "synthA_plot.png").exists()
    assert "manifest.json" in summary["files"]
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["params"]["norm"] == "max"
    assert manifest["inputs"][0]["name"] == "synthA.TXT"       # フルパスは残さない
    assert "->" in err                                           # 人間向けは標準エラー


def test_same_second_gets_suffix(capsys, tmp_path, monkeypatch):
    from datetime import datetime
    import saji.core.runner as runner

    fixed = datetime(2026, 9, 24, 14, 3, 12).astimezone()
    real = runner.execute

    def execute(*a, **kw):
        kw["now"] = lambda: fixed
        kw["export_figures"] = False
        return real(*a, **kw)

    monkeypatch.setattr("saji.cli.execute", execute)
    for _ in range(2):
        assert run_cli(capsys, "xrd-process", TXT, "--output-dir", str(tmp_path))[0] == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "20260924_140312-xrd-process", "20260924_140312-xrd-process-2"]


def test_dry_run_writes_nothing(capsys, tmp_path):
    code, out, _ = run_cli(capsys, "xrd-process", TXT, "--bg", "snip", "--dry-run", "--json",
                           "--output-dir", str(tmp_path))
    assert code == 0
    plan = json.loads(out)
    assert plan["dry_run"] is True and plan["params"]["bg"] == "snip"
    assert plan["inputs"]["raw"] == ["synthA.TXT"]
    assert not any(tmp_path.iterdir())


def test_params_file_and_manifest_rerun(capsys, tmp_path):
    params = tmp_path / "p.json"
    params.write_text(json.dumps({"norm": "max", "norm_target": 100}), encoding="utf-8")
    code, out, _ = run_cli(capsys, "xrd-process", TXT, "--params", str(params), "--norm-target", "50",
                           "--dry-run", "--json")
    plan = json.loads(out)
    assert plan["params"]["norm"] == "max" and plan["params"]["norm_target"] == 50.0   # 個別の引数が優先
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"tool": "xrd-process", "params": {"bg": "none"}}), encoding="utf-8")
    code, out, _ = run_cli(capsys, "xrd-process", TXT, "--params", str(manifest), "--dry-run", "--json")
    assert json.loads(out)["params"]["bg"] == "none"


@pytest.mark.parametrize("args", [
    ["xrd-process"],                                               # 必須の入力がない
    ["xrd-process", "no_such_file.TXT"],                           # 見つからない
    ["xrd-process", TXT, "--norm", "reference"],                   # norm_ref_pos が要る
    ["xrd-process", str(FIXTURES / "xrd" / "peaks.json")],         # 数値2列がない
])
def test_input_errors_exit_2(capsys, tmp_path, args):
    code, out, err = run_cli(capsys, *args, "--output-dir", str(tmp_path), "--json")
    assert code == 2
    res = json.loads(out)
    assert res["ok"] is False and res["exit_code"] == 2 and res["error"]
    assert "エラー" in err


def test_bad_choice_is_usage_error(capsys):
    with pytest.raises(SystemExit) as e:
        main(["xrd-process", TXT, "--bg", "magic"])
    assert e.value.code == 2
