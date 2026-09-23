"""図の元データを CSV にする（Origin などで仕上げるため）。

系列ごとに「名前 x」「名前 y」の2列を横に並べる（長さの違う系列は空欄で埋める）。
棒グラフの x は分類名のまま、誤差があれば「名前 err」列も付ける。
"""

from __future__ import annotations

import csv
import io
from typing import Any


def figure_to_csv(fig: dict[str, Any]) -> str:
    columns: list[tuple[str, list[Any]]] = []
    for i, tr in enumerate(fig.get("data", [])):
        name = str(tr.get("name") or f"trace{i + 1}")
        columns.append((f"{name} x", list(tr.get("x") or [])))
        columns.append((f"{name} y", list(tr.get("y") or [])))
        err = (tr.get("error_y") or {}).get("array")
        if err:
            columns.append((f"{name} err", list(err)))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow([c for c, _ in columns])
    n = max((len(v) for _, v in columns), default=0)
    for r in range(n):
        w.writerow(["" if r >= len(v) or v[r] is None else v[r] for _, v in columns])
    return buf.getvalue()
