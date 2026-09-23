"""xrd-overlay のゴールデン（期待値 JSON）を kaiseki-tool で作るスクリプト。

kaiseki-tool の環境で実行する（saji は import しない）:

    cd C:\\code\\kaiseki-tool
    uv run python C:\\code\\saji\\tests\\golden\\xrd-overlay\\make_golden.py

入力は tests/golden/xrd-process/*.xy（kaiseki の xrd process の出力＝処理済み .xy）。
kaiseki の overlay() を matplotlib (Agg) で実際に描かせ、描いた図の Axes から
線の y（オフセット込み）・マーカー位置・注釈位置・y 範囲を拾って JSON にする。
ケースは saji のパラメータの形（CASES）で書き、kaiseki の引数に読み替える。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import to_hex  # noqa: E402

import kaiseki.xrd.overlay as ov  # noqa: E402

HERE = Path(__file__).parent
XY = HERE.parent / "xrd-process"
FIXTURES = HERE.parent.parent / "fixtures" / "xrd"

# 線の y は間引いて保存する（全点だと大きいので、SAMPLE 点おき + min/max/sum）。
SAMPLE = 50

CASES = {
    "default": {
        "inputs": ["case1-synthA_processed.xy", "case1-synthB_processed.xy"],
        "peaks": "peaks.json",
        "params": {},
    },
    "stacked": {
        # 近い位置の帰属（Cu(111) と CuX(111) が同じピークに当たる）→ 注釈が段積みになる
        "inputs": ["case1-synthA_processed.xy", "case1-synthB_processed.xy"],
        "peaks": "peaks_close.json",
        "params": {"offset": "120"},
    },
    "bottomup_norm_top": {
        "inputs": ["case1-synthA_processed.xy", "case2-synthA_processed.xy",
                   "case2-synthB_processed.xy", "case3-synthB_processed.xy"],
        "peaks": "peaks.json",
        "params": {"normalize_each": True, "bottom_up": True, "peaks_on": "top", "gap": 1.3},
    },
    "fixed_traces": {
        "inputs": ["case1-synthA_processed.xy", "case1-synthB_processed.xy",
                   "case3-synthA_processed.xy"],
        "peaks": "peaks.json",
        "params": {
            "offset": "50", "peak_guides": False, "peak_tol": 0.2,
            "traces": [
                {"file": "case1-synthB_processed.xy", "label": "B", "color": "tab:green", "offset": 10},
                {"file": "case1-synthA_processed.xy", "label": "A"},
                {"file": "case3-synthA_processed.xy", "label": "A (ref)"},
            ],
        },
    },
}


def _sample(ys) -> dict:
    ys = [float(v) for v in ys]
    return {"n": len(ys), "min": min(ys), "max": max(ys), "sum": sum(ys),
            "sample": ys[::SAMPLE]}


def run_case(name: str, case: dict) -> dict:
    p = case["params"]
    paths = [str(XY / f) for f in case["inputs"]]
    captured: dict = {}

    orig_layout = ov.layout_peak_annotations
    orig_close = plt.close

    def layout_spy(anns, **kw):
        out = orig_layout(anns, **kw)
        captured["laid"] = out
        return out

    def close_spy(fig=None):
        captured["fig"] = fig
        return orig_close(fig)

    ov.layout_peak_annotations = layout_spy
    plt.close = close_spy
    try:
        entries = ov.resolve_inputs(paths, "*_processed.xy", p.get("traces"))
        out = HERE / f"_{name}.png"
        ov.overlay(entries, offset_mode=p.get("offset", "auto"), gap=p.get("gap", 1.10),
                   cmap=p.get("cmap", "tab10"), normalize_each=p.get("normalize_each", False),
                   bottom_up=p.get("bottom_up", False),
                   peaks=ov.load_peaks(str(FIXTURES / case["peaks"])) if case["peaks"] else None,
                   peak_tol=p.get("peak_tol", 0.3), peak_prominence=p.get("peak_prominence"),
                   peak_guides=p.get("peak_guides", True), peaks_on=p.get("peaks_on", "each"),
                   save_path=str(out))
        out.unlink(missing_ok=True)
    finally:
        ov.layout_peak_annotations = orig_layout
        plt.close = orig_close

    ax = captured["fig"].axes[0]
    drawn = [e for e in entries if "_xy" in e]
    traces = []
    data_lines = [ln for ln in ax.lines if not ln.get_label().startswith("_")]
    for e, ln in zip(drawn, data_lines):
        traces.append({
            "file": Path(e["path"]).name, "label": e["label"], "offset": float(e["_off"]),
            "color": to_hex(e["color"]),
            "y": _sample(ln.get_ydata()),
            "peaks": [{"material": q["material"], "found": q["found"],
                       **({"x": q["x"], "y": q["y"]} if q["found"] else {})}
                      for q in e.get("_peaks", [])],
        })
    markers = []
    for coll in ax.collections:
        for x, y in coll.get_offsets():
            markers.append([float(x), float(y)])
    labels = [{"text": t.get_text(), "x": float(t.xy[0]), "y": float(t.xy[1])} for t in ax.texts]
    laid = [{"material": a["material"], "x": a["x"], "y_anchor": a["y_anchor"],
             "stack_level": a["stack_level"]} for a in captured.get("laid", [])]
    return {
        "inputs": case["inputs"], "peaks": case["peaks"],
        "params": p, "traces": traces, "markers": markers, "labels": labels, "laid": laid,
        "ylim": [float(v) for v in ax.get_ylim()],
    }


def main() -> None:
    for name, case in CASES.items():
        res = run_case(name, case)
        (HERE / f"{name}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n",
                                           encoding="utf-8", newline="\n")
        print(name, "ok", len(res["traces"]), "traces")


if __name__ == "__main__":
    main()
