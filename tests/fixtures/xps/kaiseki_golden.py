"""xps-plot / xps-fit のゴールデン（数値）を kaiseki-tool で作るスクリプト。

kaiseki-tool の xps plot / fit は図（PNG・HTML）しか出さないので、図の元になる
前処理の結果（prepare_traces / prepare_fit_traces / _prepare_overlay の戻り）を JSON にする。
saji の xps-plot / xps-fit がこれと同じ数値を描くことをテストで確かめる。

kaiseki-tool の環境で実行する（saji からは import しない）:

    cd <kaiseki-tool> && uv run python <saji>/tests/fixtures/xps/kaiseki_golden.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from kaiseki.xps.fit import _prepare_overlay, load_fit_csv, prepare_fit_traces
from kaiseki.xps.plot import prepare_traces, resolve_files

HERE = Path(__file__).parent
GOLDEN = HERE.parent.parent / "golden"
EXT = HERE / "extracted"
FIT = HERE / "fit"

PLOT_CASES = {
    "survey": dict(files=["sampleA_Survey.csv", "sampleB_Survey.csv"], x_range=None,
                   window_normalize=True, offset_step=1.2),
    "c1s_window": dict(files=["sampleA_C1s.csv", "sampleB_C1s.csv", "sampleC_C1s.csv"],
                       x_range=[292, 280], window_normalize=True, offset_step=1.5),
    "no_window_normalize": dict(files=["sampleA_C1s.csv", "sampleC_C1s.csv"], x_range=[282, 290],
                                window_normalize=False, offset_step=2.0),
}

FIT_CASES = {
    "pH7_default": dict(file="fit_O1s_pH7.csv", x_range=None, normalize=False, settings={}),
    "pH7_window_annotate": dict(file="fit_O1s_pH7.csv", x_range=[527, 535], normalize=True, settings={
        "residual_mode": "panel", "annotate_peaks": True, "peak_labels": ["lattice O", "OH", "H2O"],
        "peak_annotate_offsets": [None, [-40, None]]}),
    "pH9_bom_outside_fit": dict(file="fit_O1s_pH9_bom.csv", x_range=[526, 526.9], normalize=False,
                                settings={"annotate_peaks": True}),
    "pH9_bom_default": dict(file="fit_O1s_pH9_bom.csv", x_range=None, normalize=False, settings={}),
    "pH11_preamble": dict(file="fit_O1s_pH11_preamble.csv", x_range=None, normalize=True, settings={
        "residual_mode": "none", "peak_colors": ["#000001", "#000002"], "fill_peaks": False,
        "peak_labels": {"Comp B": "OH"}}),
}

OVERLAY = dict(files=["fit_O1s_pH7.csv", "fit_O1s_pH9_bom.csv", "fit_O1s_pH11_preamble.csv"],
               x_range=[527, 535], normalize=True, offset_step=1.3,
               settings={"residual_mode": "offset", "annotate_peaks": True, "annotate_on": "all",
                         "peak_labels": ["lattice O", "OH"]})


def arr(a):
    if a is None:
        return None
    return [None if not math.isfinite(v) else float(v) for v in np.asarray(a, dtype=float)]


def trace(t):
    if t is None:
        return None
    return {
        "kind": t["kind"], "label": t["label"], "color": t["color"], "dash": t["dash"],
        "width": t["width"], "in_legend": t["in_legend"], "annotate": t["annotate"],
        "x": arr(t["x"]), "y": arr(t["y"]), "fill_base": arr(t["fill_base"]),
        "apex": None if t["apex"] is None else list(t["apex"]),
        "apex_ceiling": t["apex_ceiling"],
        "annotate_offset": t["annotate_offset"],
    }


def prepared(p):
    return {"mode": p["mode"], "residual_zero": p["residual_zero"],
            "main": [trace(t) for t in p["main"]], "residual": trace(p["residual"])}


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    for name, c in PLOT_CASES.items():
        entries = resolve_files([str(EXT / f) for f in c["files"]])
        traces = prepare_traces(entries, x_range=c["x_range"], window_normalize=c["window_normalize"],
                                offset_step=c["offset_step"])
        dump(GOLDEN / "xps-plot" / f"{name}.json",
             [{"label": t["label"], "x": arr(t["x"]), "y": arr(t["y"])} for t in traces])

    for name, c in FIT_CASES.items():
        p = prepare_fit_traces(load_fit_csv(FIT / c["file"]), x_range=c["x_range"],
                               normalize=c["normalize"], settings=c["settings"])
        dump(GOLDEN / "xps-fit" / f"{name}.json", prepared(p))

    panels = resolve_files([str(FIT / f) for f in OVERLAY["files"]])
    layers = _prepare_overlay(panels, x_range=OVERLAY["x_range"], normalize=OVERLAY["normalize"],
                              offset_step=OVERLAY["offset_step"], settings=OVERLAY["settings"])
    dump(GOLDEN / "xps-fit" / "overlay.json",
         [{"offset": lay["offset"], "title": lay["title"], "prepared": prepared(lay["prepared"])}
          for lay in layers])


if __name__ == "__main__":
    main()
