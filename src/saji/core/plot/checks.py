"""図の検査。

フォントは Arial に統一している（docs/decisions/0003）。日本語などArial に無い文字は
環境によって表示できない（Web 版の matplotlib では確実に豆腐になる）ので、図に
含まれていたら警告する。
"""

from __future__ import annotations

import re
from typing import Any, Iterator

# Arial が持たない代表的な文字（CJK・かな・全角記号）。
_NON_ARIAL = re.compile(r"[　-ヿ㐀-鿿豈-﫿＀-￯]")


def iter_texts(fig: dict[str, Any]) -> Iterator[str]:
    """図の中で表示されうる文字列を列挙する。"""
    layout = fig.get("layout", {})
    title = layout.get("title")
    if isinstance(title, dict):
        yield str(title.get("text") or "")
    for key, axis in layout.items():
        if (key.startswith("xaxis") or key.startswith("yaxis")) and isinstance(axis, dict):
            t = axis.get("title")
            if isinstance(t, dict):
                yield str(t.get("text") or "")
    for ann in layout.get("annotations") or []:
        yield str(ann.get("text") or "")
    for tr in fig.get("data", []):
        if tr.get("showlegend", True):
            yield str(tr.get("name") or "")
        for t in tr.get("text") or []:
            yield str(t)
        if tr.get("type") == "bar":
            for v in tr.get("x") or []:
                if isinstance(v, str):
                    yield v


def non_arial_texts(fig: dict[str, Any]) -> list[str]:
    """Arial で表示できない文字を含む文字列の一覧（重複なし）。"""
    return list(dict.fromkeys(t for t in iter_texts(fig) if _NON_ARIAL.search(t)))
