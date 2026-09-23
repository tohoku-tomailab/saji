"""ツールの一覧（CLI と Web の両方が参照する唯一の一覧）。

ツールを追加したら TOOL_MODULES に1行足す（docs/adding-a-tool.md）。
並び順がそのまま `saji list` と Web の一覧の順になる。
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

TOOL_MODULES = [
    "xrd_process",
    "xrd_overlay",
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
    tools = load_all()
    if name not in tools:
        raise KeyError(f"ツールがありません: {name}（saji list で一覧を確認）")
    return tools[name]


def tools_json() -> list[dict[str, Any]]:
    """Web 用の tools.json の中身。"""
    return [mod.TOOL.to_dict() for mod in load_all().values()]
