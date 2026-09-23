"""XPS 抽出CSV（x,y）の重ね描き（xps-plot）。

「1グループ = 1つのパネル」で、グループ内のCSVをオフセット付きで重ね描きする
（kaiseki-tool の xps/plot.py、元は ref/2/xps_plotter.py の構成を踏襲）。x軸は結合
エネルギーなので既定で反転（大→小）。サーベイ全域で正規化済みのデータを狭い窓で見る
ときは表示x範囲内で Min-Max 再正規化する（window_normalize、既定ON）。

トレースの前処理（クリップ・再正規化・オフセット）は kaiseki-tool の prepare_traces と
同じ数値になるようにしてある。複数パネルは軸の domain で縦に並べ、パネルの見出しは
図の上端からの位置（paper 座標）に置いた注釈で表す。
"""

from __future__ import annotations

import io
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

import numpy as np

from ...core.plot import add_annotation, add_line, new_figure, panel_domains, set_axis
from ...core.plot.style import series_color
from ...core.tableio import decode_text
from . import DEFAULT_OFFSET_STEP, DEFAULT_XLABEL, DEFAULT_YLABEL

PANEL_GAP_PX = 130      # パネル間の空き（下のパネルの見出し + 上のパネルの x 軸名が入る分）


# ============================================================ 読み込み
def load_xy_csv(data: bytes) -> tuple[np.ndarray, np.ndarray]:
    """x,y ヘッダ付きCSV（無ければ先頭2列）を読む。"""
    import pandas as pd

    df = pd.read_csv(io.StringIO(decode_text(data)))
    cols = [str(c).strip().lower() for c in df.columns]
    if "x" in cols and "y" in cols:
        xs = df.iloc[:, cols.index("x")]
        ys = df.iloc[:, cols.index("y")]
    else:
        if df.shape[1] < 2:
            raise ValueError("2列データとして読めません")
        xs, ys = df.iloc[:, 0], df.iloc[:, 1]
    return (pd.to_numeric(xs, errors="coerce").to_numpy(),
            pd.to_numeric(ys, errors="coerce").to_numpy())


# ============================================================ 前処理
def clip_to_x_range(x: np.ndarray, y: np.ndarray,
                    x_range: Sequence[float] | None) -> tuple[np.ndarray, np.ndarray]:
    """表示x範囲内のデータ点だけを取り出す。"""
    if x_range is None:
        return x, y
    lo, hi = min(x_range), max(x_range)
    m = (x >= lo) & (x <= hi)
    return x[m], y[m]


def renormalize_y(y: np.ndarray) -> np.ndarray:
    """y を 0-1 に Min-Max 再正規化する（値幅0なら全て0）。"""
    if len(y) == 0:
        return y
    span = float(np.nanmax(y) - np.nanmin(y))
    if span == 0:
        return np.zeros_like(y)
    return (y - np.nanmin(y)) / span


def prepare_traces(
    entries: Sequence[Mapping[str, Any]],
    *,
    x_range: Sequence[float] | None = None,
    window_normalize: bool = True,
    offset_step: float = DEFAULT_OFFSET_STEP,
) -> tuple[list[dict[str, Any]], list[str]]:
    """1グループ分の entry 群（{name, data, label, color}）を描画用トレースへ変換する。

    クリップ → （必要なら）再正規化 → n本目に n*offset_step を加算 → 色決定。
    読めないファイル・範囲内にデータが無いファイルは飛ばし、警告文を2つ目の戻り値で返す。
    """
    traces: list[dict[str, Any]] = []
    warnings: list[str] = []
    for i, e in enumerate(entries):
        # 表示範囲外や読み込み失敗で飛ばしても、オフセットと色は元の並び順 i で決める（kaiseki-tool と同じ）
        try:
            x, y = load_xy_csv(e["data"])
        except Exception as exc:  # noqa: BLE001 - 壊れたCSVは飛ばして続ける
            warnings.append(f"読み込みをスキップしました {e['name']}: {exc}")
            continue
        if window_normalize:
            x, y = clip_to_x_range(x, y, x_range)
            if len(x) == 0:
                warnings.append(f"表示x範囲内にデータがありません: {e['name']}")
                continue
            y = renormalize_y(y)
        traces.append(dict(
            x=x, y=y + i * offset_step, name=e["name"],
            label=e["label"], color=series_color(i, e.get("color")),
        ))
    return traces, warnings


def region_of(filename: str) -> str:
    """ファイル名から領域名を推定する（stem の '_' 区切り末尾。例 sampleA_C1s.csv → C1s）。"""
    stem = PurePosixPath(filename).stem
    return stem.split("_")[-1] if "_" in stem else stem


def infer_group_title(entries: Sequence[Mapping[str, Any]], index: int) -> str:
    """グループタイトルを先頭ファイルの名前から推定する（stem の '_' 区切り末尾）。"""
    if not entries:
        return f"Group {index + 1}"
    return region_of(entries[0]["name"])


# ============================================================ 図
def _axis_keys(i: int) -> tuple[str, str, str, str]:
    """i 番目のパネルの (xaxis キー, yaxis キー, x 参照, y 参照)。"""
    n = "" if i == 0 else str(i + 1)
    return f"xaxis{n}", f"yaxis{n}", f"x{n}", f"y{n}"


def plot_figure(
    groups: Sequence[Sequence[dict[str, Any]]],
    st: dict,
    *,
    titles: Sequence[str],
    fig_title: str | None = None,
    axis_ranges: Sequence[Mapping[str, Any]] | None = None,
    invert_x: bool = True,
    markers: bool = False,
    xlabel: str = DEFAULT_XLABEL,
    ylabel: str = DEFAULT_YLABEL,
    show_yticks: bool = False,
    legend_outside: bool = True,
) -> dict[str, Any]:
    """前処理済みトレースのグループ群を、縦に並べたパネルに描く。

    groups の各要素は prepare_traces の戻り（1グループ分のトレース）。1グループなら
    見出しを図のタイトルにし、複数グループならパネルごとに見出しの注釈を付ける。
    """
    n = max(1, len(groups))
    ranges = list(axis_ranges or [])
    while len(ranges) < n:
        ranges.append({})
    single = n == 1
    height = st["height"] * n
    fig = new_figure(st, title=(titles[0] if titles else None) if single else fig_title,
                     height=height, legend="outside" if legend_outside else "inside")
    margin = fig["layout"]["margin"]
    plot_h = height - margin["t"] - margin["b"]
    domains = panel_domains(n, gap=min(0.3, PANEL_GAP_PX / plot_h)) if n > 1 else [[0.0, 1.0]]

    for gi in range(n):
        traces = groups[gi] if gi < len(groups) else []
        xk, yk, xr, yr = _axis_keys(gi)
        for tr in traces:
            add_line(fig, tr["x"], tr["y"], tr["label"], st, color=tr["color"],
                     markers=markers, marker_size=st["marker"] * 0.7, xaxis=xr, yaxis=yr)
        x_range = ranges[gi].get("x_range")
        set_axis(fig, xk, st, title=xlabel, range=x_range, reversed=invert_x,
                 anchor=yr if gi else None)
        set_axis(fig, yk, st, title=ylabel, range=ranges[gi].get("y_range"),
                 show_ticklabels=show_yticks, domain=domains[gi] if n > 1 else None,
                 anchor=xr if gi else None)
        if not single:
            add_annotation(fig, 0.5, domains[gi][1], titles[gi] if gi < len(titles) else "", st,
                           xref="paper", yref="paper", yanchor="bottom", yshift=6,
                           size=st["axis_title"])
        if not traces:
            add_annotation(fig, 0.5, (domains[gi][0] + domains[gi][1]) / 2, "No valid data", st,
                           xref="paper", yref="paper", yanchor="middle")
    return fig
