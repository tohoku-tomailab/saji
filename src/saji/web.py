"""Web（Pyodide）から呼ぶ入口。web/worker.js だけが使う。

JS から受け取るもの:
  files   … [{input: 入力名, name: ファイル名, data: Uint8Array}, ...]
  params  … {名前: 値}（フォームの値。空欄は送らない）
返すもの:
  run_tool() … 要約とプレビューの図を入れた JSON 文字列
  last_zip() … 直前の実行の zip（出力フォルダと同じ構成）
"""

from __future__ import annotations

import json
import traceback
from typing import Any

from . import registry
from .core.runner import clock_with_offset, execute, to_zip
from .core.tool import InputError, InputFile

_last: dict[str, Any] = {}


def run_tool(name: str, files: list[dict[str, Any]], params: dict[str, Any],
             tz_offset_minutes: int = 0) -> str:
    """ツールを実行して結果の JSON 文字列を返す（例外も JSON で返す）。"""
    _last.clear()
    try:
        mod = registry.get(name)
        inputs: dict[str, list[InputFile]] = {i.name: [] for i in mod.TOOL.inputs}
        for f in files:
            data = f["data"]
            data = data.to_bytes() if hasattr(data, "to_bytes") else bytes(data)
            inputs.setdefault(f["input"], []).append(InputFile(name=str(f["name"]), data=data))
        ex = execute(mod, inputs, params, runtime="web",
                     now=clock_with_offset(int(tz_offset_minutes)))
    except InputError as exc:
        return json.dumps({"ok": False, "kind": "input", "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "kind": "internal", "error": f"{type(exc).__name__}: {exc}",
                           "traceback": traceback.format_exc()}, ensure_ascii=False)
    _last["zip"] = to_zip(ex)
    summary = ex.summary()
    summary["zip_name"] = f"{ex.folder_name}.zip"
    summary["previews"] = ex.previews
    return json.dumps(summary, ensure_ascii=False)


def last_zip():
    """直前の実行の zip を JS の Uint8Array で返す。"""
    from pyodide.ffi import to_js  # type: ignore[import-not-found]

    return to_js(_last.get("zip", b""))
