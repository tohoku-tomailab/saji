"""ツールの一覧（CLI と Web の両方が参照する唯一の一覧）。

ツールを追加したら TOOL_MODULES に1行足す（docs/adding-a-tool.md）。
モジュール名はツール名の - を _ にしたもの（xrd-process → xrd_process）。
並び順がそのまま `saji list` と Web の一覧の順になる。
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

TOOL_MODULES = [
    "xrd_process",
    "xrd_overlay",
    "xps_extract",
    "xps_plot",
    "xps_fit",
    "co2rr_plot",
    "echem_extract",
    "mpt_cycle",
]


def load_all() -> dict[str, ModuleType]:
    """ツール名 → モジュール（TOOL と run を持つ）。"""
    out: dict[str, ModuleType] = {}
    for mod_name in TOOL_MODULES:
        mod = importlib.import_module(f"saji.tools.{mod_name}")
        name = mod.TOOL.name
        if name in out:
            raise RuntimeError(f"ツール名が重複しています: {name}")
        out[name] = mod
    return out


def get(name: str) -> ModuleType:
    """ツール名 → モジュール。そのツールのモジュールだけを import する
    （Web では、ほかのツールが使うパッケージがまだ読み込まれていないことがあるため）。
    モジュール名はツール名の - を _ にしたもの。"""
    mod_name = name.replace("-", "_")
    if mod_name not in TOOL_MODULES:
        raise KeyError(f"ツールがありません: {name}（saji list で一覧を確認）")
    mod = importlib.import_module(f"saji.tools.{mod_name}")
    if mod.TOOL.name != name:
        raise RuntimeError(f"{mod_name}.py の TOOL.name は {name} にしてください（今は {mod.TOOL.name}）")
    return mod


def tools_json() -> list[dict[str, Any]]:
    """Web 用の tools.json の中身。"""
    return [mod.TOOL.to_dict() for mod in load_all().values()]
