"""core（ツール定義・パラメータ・実行・manifest）のテスト。"""

from __future__ import annotations

import io
import json
import types
import zipfile

import pytest

from saji.core.runner import execute, resolve_params, to_zip
from saji.core.tool import FileInput, InputError, InputFile, Param, Result, Tool


def test_param_coerce_types():
    assert Param("n", int).coerce("3") == 3
    assert Param("n", int).coerce(4.0) == 4
    with pytest.raises(InputError):
        Param("n", int).coerce("3.5")
    assert Param("f", float).coerce("1e6") == 1e6
    assert Param("b", bool).coerce("false") is False
    assert Param("c", choices=("a", "b")).coerce("b") == "b"
    with pytest.raises(InputError):
        Param("c", choices=("a", "b")).coerce("z")
    assert Param("r", "range").coerce("526,538") == [526.0, 538.0]
    assert Param("r", "range").coerce(",538") == [None, 538.0]
    assert Param("j", "json").coerce('{"a": 1}') == {"a": 1}
    assert Param("n", int).coerce("") is None


def test_param_bounds():
    with pytest.raises(InputError):
        Param("n", int, min=1).coerce(0)


def test_tool_rejects_duplicate_names():
    with pytest.raises(ValueError):
        Tool("t", "s", inputs=[FileInput("a")], params=[Param("a")])


def _dummy_module():
    tool = Tool("dummy", "テスト用", inputs=[FileInput("src", accept=[".txt"], multiple=True)],
                params=[Param("scale", float, 2.0)])

    def run(inputs, params):
        r = Result()
        total = sum(len(f.data) for f in inputs["src"]) * params["scale"]
        r.add_file("out.txt", f"{total}\n")
        r.data["total"] = total
        r.add_figure("fig", {"data": [{"type": "scatter", "x": [0, 1], "y": [1, 2], "name": "線"}],
                             "layout": {}}, export=False)
        return r

    return types.SimpleNamespace(TOOL=tool, run=run)


def test_resolve_params_defaults_and_unknown():
    mod = _dummy_module()
    assert resolve_params(mod.TOOL, {}) == {"scale": 2.0}
    assert resolve_params(mod.TOOL, {"scale": "3"}) == {"scale": 3.0}
    with pytest.raises(InputError):
        resolve_params(mod.TOOL, {"nope": 1})


def test_execute_manifest_and_zip():
    mod = _dummy_module()
    ex = execute(mod, {"src": [InputFile("a.txt", b"abc"), InputFile("b.csv", b"de")]}, {})
    names = [f.path for f in ex.files]
    assert names == ["out.txt", "manifest.json"]
    m = json.loads(ex.files[-1].data)
    assert m["tool"] == "dummy" and m["runtime"] == "cli"
    assert m["params"] == {"scale": 2.0}
    assert [i["name"] for i in m["inputs"]] == ["a.txt", "b.csv"]
    assert m["outputs"] == ["out.txt"]
    # 想定外の拡張子と、日本語を含む図は警告になる
    assert any("b.csv" in w for w in m["warnings"])
    assert any("Arial" in w for w in ex.result.warnings)
    assert ex.result.data["total"] == 10.0
    with zipfile.ZipFile(io.BytesIO(to_zip(ex))) as zf:
        assert sorted(zf.namelist()) == sorted(f"{ex.folder_name}/{n}" for n in names)


def test_execute_missing_required_input():
    with pytest.raises(InputError):
        execute(_dummy_module(), {"src": []}, {})


def test_registry_names_match_modules():
    from saji import registry

    for name, mod in registry.load_all().items():
        assert registry.get(name) is mod
        assert mod.__name__.endswith(name.replace("-", "_"))
