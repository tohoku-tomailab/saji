"""XRD（X線回折）の手法知識。

数値処理は kaiseki-tool の xrd/process.py（元は ref/xrd_process.py）と等価に保つ。
重ね描き（xrd-overlay）は kaiseki-tool の xrd/overlay.py と等価に保つ（末尾の「重ね描き」）。
入力形式は docs/data-formats.md の「Rigaku SmartLab .TXT」「2列 .xy」を参照。

処理順序:  ビニング(任意) -> バックグラウンド除去 -> スムージング -> 規格化
  背景を先に引くので最終曲線のベースラインは≒0。ピーク検出はこの最終曲線に対して
  prominence（周囲からの立ち上がり量）で行う。

図の約束（docs/plotting.md）:
  - x軸は 2θ。規格化したときは左軸=生データと背景（counts）、右軸=規格化後。
  - ピーク帰属（参照ピーク）は、ピークが立っている位置にマーカーと物質名を付ける。
    近い位置の注釈は上方向に段積みする。
  - 重ね描きは1つの軸にオフセットで積む（既定は先頭のファイルが最上段）。
"""

from __future__ import annotations

import json
from typing import Any, Sequence

import numpy as np

from ..core.plot import (
    add_annotation, add_hline, add_line, add_vline, new_figure, set_axis,
)
from ..core.plot.style import css_color, marker_symbol, tab10
from ..core.tableio import load_numeric_pairs, load_xy_text

XLABEL = "2θ (deg)"

# numpy 2.0 で trapz -> trapezoid に改名。
_trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz")


# ============================================================ 読み込み
def parse_metadata(text: str) -> dict[str, str]:
    """SmartLab のヘッダから測定条件をゆるく拾う（表示用）。"""
    meta = {}
    keys = ["Sample", "Start", "Stop", "Step", "X-Ray", "ScanningMode", "Goniometer", "Attachment"]
    for line in text.splitlines():
        for k in keys:
            if line.startswith(k):
                meta[k] = line[len(k):].strip()
    return meta


def load_smartlab(text: str) -> tuple[np.ndarray, np.ndarray, dict[str, str]]:
    """SmartLab .TXT の文字列から (2θ, 強度, meta) を取り出す。

    「数値2つだけの行」をデータ行とみなすので、ヘッダ行数が変わっても追従する。
    """
    return (*load_numeric_pairs(text), parse_metadata(text))


def load_peaks(data: bytes) -> list[tuple[float, str, str, str]]:
    """ピーク表 JSON（[[2θ, 物質名, マーカー, 色], ...]）を読む。"""
    rows = json.loads(data.decode("utf-8-sig"))
    out = []
    for i, row in enumerate(rows):
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise ValueError(f"ピーク表の {i + 1} 行目は [2θ, 物質名, マーカー, 色] の形にしてください: {row}")
        pos, name = float(row[0]), str(row[1])
        marker = str(row[2]) if len(row) > 2 else "v"
        color = str(row[3]) if len(row) > 3 else "tab:red"
        out.append((pos, name, marker, color))
    return out


# ============================================================ 前処理
def rebin(x, y, factor):
    """factor 点ずつ平均してビニング（点数を減らしノイズを均す）。"""
    if not factor or factor <= 1:
        return x, y
    n = (len(y) // factor) * factor
    return x[:n].reshape(-1, factor).mean(axis=1), y[:n].reshape(-1, factor).mean(axis=1)


def estimate_background(x, y, method="arpls", **kwargs):
    """背景を推定して返す（差し引きはしない）。

      none  -> 全ゼロ
      arpls -> kwargs: lam(既定1e6)
      snip  -> kwargs: max_half_window(既定120), smooth_half_window(既定3)
    """
    method = (method or "none").lower()
    if method == "none":
        return np.zeros_like(y)
    from pybaselines import Baseline

    fitter = Baseline(x_data=x)
    if method == "arpls":
        return fitter.arpls(y, lam=kwargs.get("lam", 1e6))[0]
    if method == "snip":
        return fitter.snip(
            y,
            max_half_window=kwargs.get("max_half_window", 120),
            smooth_half_window=kwargs.get("smooth_half_window", 3),
            decreasing=True,
        )[0]
    raise ValueError(f"未対応の背景手法: {method}（none/arpls/snip）")


def smooth(x, y, method="none", **kwargs):
    """平滑化。none / savgol(window_length, polyorder) / moving_average(window) / gaussian(sigma)。"""
    method = (method or "none").lower()
    if method == "none":
        return y.copy()
    if method == "savgol":
        from scipy.signal import savgol_filter

        w = int(kwargs.get("window_length", 11))
        p = int(kwargs.get("polyorder", 3))
        if w % 2 == 0:
            w += 1                       # 奇数に矯正
        w = min(w, len(y) - (1 - len(y) % 2))
        p = min(p, w - 1)
        return savgol_filter(y, window_length=w, polyorder=p)
    if method == "moving_average":
        from scipy.ndimage import uniform_filter1d

        return uniform_filter1d(y, size=max(1, int(kwargs.get("window", 9))), mode="nearest")
    if method == "gaussian":
        from scipy.ndimage import gaussian_filter1d

        return gaussian_filter1d(y, sigma=float(kwargs.get("sigma", 2.0)), mode="nearest")
    raise ValueError(f"未対応の平滑化手法: {method}（none/savgol/moving_average/gaussian）")


def normalize(x, y, method="none", target=1.0, ref_pos=None, ref_tol=0.3):
    """最終曲線を規格化する。戻り値は (規格化後y, 使ったスケール, 参照情報dict)。

      none      -> そのまま
      max       -> 最大値を target に（100 で % 表示）
      area      -> 積分強度（負の裾は数えない）を target に
      reference -> ref_pos ± ref_tol の最大ピーク高さを target に（Cu(111) 基準など）
    スケールが 0 / 無効のときは規格化せず、info["skipped"] = True を返す。
    """
    method = (method or "none").lower()
    info: dict[str, Any] = {"method": method, "target": target}
    if method == "none":
        return y.copy(), 1.0, info

    if method == "max":
        scale = float(np.max(y))
        info["at"] = float(x[int(np.argmax(y))])
    elif method == "area":
        scale = float(_trapz(np.clip(y, 0, None), x))
    elif method == "reference":
        if ref_pos is None:
            raise ValueError("規格化 reference には基準ピークの位置（norm_ref_pos）が必要です")
        m = (x > ref_pos - ref_tol) & (x < ref_pos + ref_tol)
        if not m.any():
            raise ValueError(f"参照位置 {ref_pos}° が測定範囲外です")
        seg = y[m]
        scale = float(np.max(seg))
        j = np.where(m)[0][int(np.argmax(seg))]
        info["at"] = float(x[j])
        info["ref_pos"] = ref_pos
    else:
        raise ValueError(f"未対応の規格化手法: {method}（none/max/area/reference）")

    if not np.isfinite(scale) or scale == 0:
        info["skipped"] = True
        return y.copy(), 1.0, info
    info["scale"] = scale
    return y / scale * target, scale, info


def process(x, y, *, bin_factor=None, bg_method="arpls", bg_kwargs=None,
            smooth_method="none", smooth_kwargs=None, norm_method="none", norm_kwargs=None):
    """1本のパターンを処理して結果を dict で返す（ビニング→背景→平滑化→規格化）。"""
    bg_kwargs = bg_kwargs or {}
    smooth_kwargs = smooth_kwargs or {}
    norm_kwargs = norm_kwargs or {}
    x, y_raw = rebin(x, y, bin_factor)
    background = estimate_background(x, y_raw, bg_method, **bg_kwargs)
    y_corrected = y_raw - background
    y_smoothed = smooth(x, y_corrected, smooth_method, **smooth_kwargs)
    y_final, norm_scale, norm_info = normalize(x, y_smoothed, norm_method, **norm_kwargs)
    return dict(
        x=x, y_raw=y_raw, background=background, y_corrected=y_corrected,
        y_smoothed=y_smoothed, y_final=y_final,
        bg_method=bg_method, bg_kwargs=bg_kwargs,
        smooth_method=smooth_method, smooth_kwargs=smooth_kwargs,
        norm_method=norm_method, norm_kwargs=norm_kwargs,
        norm_scale=norm_scale, norm_info=norm_info, bin_factor=bin_factor,
    )


def format_xy(res: dict) -> str:
    """最終曲線 (x, y_final) を2列テキストにする（np.savetxt 互換、fmt=%.6f）。"""
    import io

    hdr = (f"2theta  intensity  | bg={res['bg_method']}{res['bg_kwargs']} "
           f"smooth={res['smooth_method']}{res['smooth_kwargs']} "
           f"norm={res['norm_method']}{res['norm_kwargs']} bin={res['bin_factor']}")
    buf = io.StringIO()
    np.savetxt(buf, np.column_stack([res["x"], res["y_final"]]), header=hdr, fmt="%.6f")
    return buf.getvalue()


# ============================================================ ピーク帰属
def find_assignment_peaks(x, y, assignments, tol=0.3, prominence=None):
    """各参照位置の ±tol 以内に、prominence 以上の立ち上がりを持つピークがあればヒット。

    assignments: [(位置2θ, 物質名, マーカー, 色), ...]
    prominence=None なら MAD からノイズを見積もって 3σ を閾値にする。
    戻り値: [{found, x, y, material, marker, color, target}, ...]
    """
    from scipy.signal import find_peaks

    y = np.asarray(y)
    if prominence is None:
        med = np.median(y)
        mad = np.median(np.abs(y - med))
        noise = 1.4826 * mad if mad > 0 else (np.std(y) or 1.0)
        prominence = 3 * noise
    idx, _ = find_peaks(y, prominence=prominence)
    idx = np.asarray(idx)
    out = []
    for pos, material, marker, color in assignments:
        rec = dict(found=False, material=material, marker=marker, color=color, target=float(pos))
        if idx.size:
            cand = idx[np.abs(x[idx] - pos) <= tol]
            if cand.size:
                j = cand[np.argmax(y[cand])]
                rec.update(found=True, x=float(x[j]), y=float(y[j]))
        out.append(rec)
    return out


def _annotation_x_half(material, x_margin_deg=0.5, deg_per_char=0.11):
    """ラベル文字列から、注釈ボックスの半幅(deg)を見積もる。"""
    return max(x_margin_deg, len(material) * deg_per_char)


def _boxes_overlap(x1_lo, x1_hi, y1_lo, y1_hi, x2_lo, x2_hi, y2_lo, y2_hi):
    return not (x1_hi <= x2_lo or x2_hi <= x1_lo or y1_hi <= y2_lo or y2_hi <= y1_lo)


def layout_peak_annotations(annotations, *, y_span, step_frac=0.11, x_margin_deg=0.5,
                            deg_per_char=0.11):
    """2θ が近い帰属注釈（マーカー+文字）が重なる場合、上方向に段積みする。

    annotations の各要素は x, y_base, material を含む dict。戻り値は同順で
    y_anchor（マーカー位置）と stack_level を付けた dict のリスト。
    """
    if not annotations:
        return []
    y_step = step_frac * (float(y_span) if y_span > 0 else 1.0)
    block_h = y_step * 1.25
    placed, laid = [], []
    ordered = sorted(annotations, key=lambda a: a["x"])
    for ann in ordered:
        x_half = _annotation_x_half(ann["material"], x_margin_deg, deg_per_char)
        x_lo, x_hi = ann["x"] - x_half, ann["x"] + x_half
        level = 0
        while True:
            y_anchor = ann["y_base"] + level * y_step
            y_lo, y_hi = y_anchor, y_anchor + block_h
            if not any(_boxes_overlap(x_lo, x_hi, y_lo, y_hi, *p) for p in placed):
                break
            level += 1
        placed.append((x_lo, x_hi, y_lo, y_hi))
        laid.append({**ann, "y_anchor": y_anchor, "stack_level": level})
    by_id = {id(a): r for a, r in zip(ordered, laid)}
    return [by_id[id(a)] for a in annotations]


def draw_peak_marks(fig, st, laid, *, yaxis="y", marker_size=None) -> None:
    """段積み済みの注釈（マーカー + 物質名）を図に描く。"""
    for ann in laid:
        color = css_color(ann["color"])
        add_line(fig, [ann["x"]], [ann["y_anchor"]], ann["material"], st, lines=False,
                 markers=True, marker_symbol=marker_symbol(ann["marker"]), color=color,
                 marker_size=marker_size or st["marker"] * 1.4, yaxis=yaxis, showlegend=False)
        add_annotation(fig, ann["x"], ann["y_anchor"], ann["material"], st, color=color,
                       yref=yaxis, yanchor="bottom", yshift=st["marker"] + 2)


# ============================================================ 図
def _processed_label(res: dict) -> str:
    parts = []
    if res["bg_method"] != "none":
        parts.append("bg-subtracted")
    if res["smooth_method"] != "none":
        parts.append(res["smooth_method"])
    return "processed" + (f" ({', '.join(parts)})" if parts else "")


def _ymax(*arrays, pad=1.0) -> float:
    vals = [float(np.nanmax(a)) for a in arrays if a is not None and len(a)]
    ymax = max(vals) if vals else 1.0
    if not np.isfinite(ymax) or ymax <= 0:
        ymax = 1.0
    return ymax * pad


def process_figure(res: dict, st: dict, *, title: str, peaks=None, show_raw=True,
                   show_background=True, peak_tol=0.3, peak_prominence=None):
    """前処理結果の図を作る。戻り値は (図, ピーク検出結果)。

    規格化ありなら左軸=生データ・背景（counts）、右軸=規格化後。
    """
    x, final = res["x"], res["y_final"]
    has_bg = res["bg_method"] != "none"
    normed = res["norm_method"] != "none"
    sub = (f"bg={res['bg_method']} {res['bg_kwargs']}  smooth={res['smooth_method']} "
           f"{res['smooth_kwargs']}  norm={res['norm_method']} {res['norm_kwargs']}")
    fig = new_figure(st, title=title, subtitle=sub, legend="inside")
    left: list[np.ndarray] = []
    raw_color, bg_color = "#b0c4de", "#ffa500"   # lightsteelblue / orange

    if show_raw and (normed or has_bg):
        add_line(fig, x, res["y_raw"], "raw", st, color=raw_color, width=st["line_thin"])
        left.append(res["y_raw"])
    if show_background and has_bg:
        add_line(fig, x, res["background"], f"background ({res['bg_method']})", st,
                 color=bg_color, dash="dash", width=st["line_thin"])
        left.append(res["background"])

    if normed:
        target = res["norm_info"].get("target", 1.0)
        add_line(fig, x, final, f"normalized ({res['norm_method']}, target={target:g})", st,
                 color="#ff7f0e", yaxis="y2")
        peak_axis, peak_top = "y2", _ymax(final, pad=1.15)
        left_top = _ymax(*(left or [res["y_raw"]]))
    else:
        add_line(fig, x, final, _processed_label(res), st, color="#1f77b4")
        left.append(final)
        peak_axis, peak_top = "y", None
        left_top = _ymax(*left)

    found = []
    if peaks:
        found = find_assignment_peaks(x, final, peaks, tol=peak_tol, prominence=peak_prominence)
        yr = float(final.max() - final.min()) or 1.0
        anns = [dict(x=p["x"], y_base=p["y"] + 0.05 * yr, material=p["material"],
                     marker=p["marker"], color=p["color"]) for p in found if p["found"]]
        laid = layout_peak_annotations(anns, y_span=yr)
        draw_peak_marks(fig, st, laid, yaxis=peak_axis)
        if laid:
            top = max(a["y_anchor"] for a in laid) + 0.11 * yr * 1.5
            if peak_axis == "y2":
                peak_top = max(peak_top, top)
            else:
                left_top = max(left_top, top)

    set_axis(fig, "xaxis", st, title=XLABEL)
    set_axis(fig, "yaxis", st, title="Intensity (counts)", range=[0, left_top], mirror=not normed)
    if normed:
        target = res["norm_info"].get("target", 1.0)
        set_axis(fig, "yaxis2", st, title=f"Normalized intensity (target={target:g})",
                 range=[0, peak_top], overlaying="y", side="right", color="#ff7f0e")
    return fig, found


# ============================================================ 重ね描き（xrd-overlay）
# kaiseki-tool の xrd/overlay.py と等価。処理済み .xy（2列: 2θ 強度）を複数本、
# 1つの軸にオフセットを付けて重ねる（ウォーターフォール）。
OVERLAY_YLABEL = "Intensity (offset)"
OVERLAY_GAP = 1.10

# matplotlib の tab20 / viridis の色（run() で matplotlib を読み込まずに済むよう値を写してある）。
# viridis は 256 色の表（#rrggbb の rrggbb を連結）。matplotlib の cmap(v) と同じく
# index = min(int(v * 256), 255) で引く。
_TAB20 = [
    "#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78", "#2ca02c", "#98df8a", "#d62728", "#ff9896",
    "#9467bd", "#c5b0d5", "#8c564b", "#c49c94", "#e377c2", "#f7b6d2", "#7f7f7f", "#c7c7c7",
    "#bcbd22", "#dbdb8d", "#17becf", "#9edae5",
]
_VIRIDIS = (
    "44015444025645045745055946075a46085c460a5d460b5e470d60470e6147106347116447136548146748"
    "166848176948186a481a6c481b6d481c6e481d6f481f70482071482173482374482475482576482677482878"
    "482979472a7a472c7a472d7b472e7c472f7d46307e46327e46337f463480453581453781453882443983443a"
    "83443b84433d84433e85423f854240864241864142874144874045884046883f47883f48893e49893e4a893e"
    "4c8a3d4d8a3d4e8a3c4f8a3c508b3b518b3b528b3a538b3a548c39558c39568c38588c38598c375a8c375b8d"
    "365c8d365d8d355e8d355f8d34608d34618d33628d33638d32648e32658e31668e31678e31688e30698e306a"
    "8e2f6b8e2f6c8e2e6d8e2e6e8e2e6f8e2d708e2d718e2c718e2c728e2c738e2b748e2b758e2a768e2a778e2a"
    "788e29798e297a8e297b8e287c8e287d8e277e8e277f8e27808e26818e26828e26828e25838e25848e25858e"
    "24868e24878e23888e23898e238a8d228b8d228c8d228d8d218e8d218f8d21908d21918c20928c20928c2093"
    "8c1f948c1f958b1f968b1f978b1f988b1f998a1f9a8a1e9b8a1e9c891e9d891f9e891f9f881fa0881fa1881f"
    "a1871fa28720a38620a48621a58521a68522a78522a88423a98324aa8325ab8225ac8226ad8127ad8128ae80"
    "29af7f2ab07f2cb17e2db27d2eb37c2fb47c31b57b32b67a34b67935b77937b87838b9773aba763bbb753dbc"
    "743fbc7340bd7242be7144bf7046c06f48c16e4ac16d4cc26c4ec36b50c46a52c56954c56856c66758c7655a"
    "c8645cc8635ec96260ca6063cb5f65cb5e67cc5c69cd5b6ccd5a6ece5870cf5773d05675d05477d1537ad151"
    "7cd2507fd34e81d34d84d44b86d54989d5488bd6468ed64590d74393d74195d84098d83e9bd93c9dd93ba0da"
    "39a2da37a5db36a8db34aadc32addc30b0dd2fb2dd2db5de2bb8de29bade28bddf26c0df25c2df23c5e021c8"
    "e020cae11fcde11dd0e11cd2e21bd5e21ad8e219dae319dde318dfe318e2e418e5e419e7e419eae51aece51b"
    "efe51cf1e51df4e61ef6e620f8e621fbe723fde725"
)
_QUALITATIVE = {"tab10": 10, "tab20": 20}
CMAPS = ("tab10", "tab20", "viridis")


def _viridis(v: float) -> str:
    i = min(int(v * 256), 255)
    return "#" + _VIRIDIS[i * 6:i * 6 + 6]


def assign_colors(n: int, cmap: str = "tab10") -> tuple[list[str], str]:
    """n 本の系列に色を割り当てる。戻り値は (色のリスト, 実際に使った色表の名前)。

    tab10 / tab20（質的）は順に巡回、viridis（連続）は両端を含めて等間隔に取る。
    質的な色表で本数が足りないとき（tab10 で 11 本以上など）は viridis に切り替える。
    """
    name = cmap
    if name in _QUALITATIVE and n > _QUALITATIVE[name]:
        name = "viridis"
    if name == "tab10":
        return [tab10(i) for i in range(n)], name
    if name == "tab20":
        return [_TAB20[i % len(_TAB20)] for i in range(n)], name
    if name == "viridis":
        return [_viridis(i / max(1, n - 1)) for i in range(n)], name
    raise ValueError(f"未対応の色表: {cmap}（{', '.join(CMAPS)}）")


def load_xy(text: str) -> tuple[np.ndarray, np.ndarray]:
    """2列 .xy（2θ 強度。'#' 以降はコメント）を読む。xrd-process の _processed.xy と同じ形。"""
    return load_xy_text(text)


def overlay_step(curves: Sequence[tuple[Any, Any]], offset: str | float = "auto",
                 gap: float = OVERLAY_GAP) -> float:
    """オフセットの刻み。

    "auto" → gap ×（全系列の中で最大の y のレンジ）。等間隔で重ならない。
    数値   → その値をそのまま刻みにする。
    """
    if offset == "auto":
        ranges = [float(np.nanmax(y) - np.nanmin(y)) for _, y in curves]
        return gap * (max(ranges) if ranges else 1.0)
    return float(offset)


def _nan_extent(arrays) -> tuple[float, float]:
    """配列群の有限値の最小・最大（無ければ 0, 1）。"""
    lo, hi = np.inf, -np.inf
    for a in arrays:
        a = np.asarray(a, dtype=float)
        a = a[np.isfinite(a)]
        if a.size:
            lo, hi = min(lo, float(a.min())), max(hi, float(a.max()))
    if not np.isfinite(lo):
        return 0.0, 1.0
    return lo, hi


def overlay_figure(traces: list[dict], st: dict, *, offset: str | float = "auto",
                   gap: float = OVERLAY_GAP, cmap: str = "tab10", normalize_each: bool = False,
                   bottom_up: bool = False, peaks=None, peak_tol: float = 0.3,
                   peak_prominence: float | None = None, peak_guides: bool = True,
                   peaks_on: str = "each", title: str | None = None, xlim=None,
                   xlabel: str | None = None, ylabel: str | None = None,
                   legend: str = "inside"):
    """重ね描き（ウォーターフォール）の図を作る。戻り値は (図, 情報 dict)。

    traces: 描く順の [{label, x, y, color(None 可), offset(None 可)}, ...]。
      color / offset が None の系列は自動（色は cmap、オフセットは 刻み × 段番号）。
    既定（top-down）は traces の先頭を最上段に積む。bottom_up=True で先頭を最下段に。
    normalize_each=True なら、重ねる前に各系列を最大値で割る（最大が 0 / 無効なら割らない）。
    peaks（[(2θ, 物質名, マーカー, 色), ...]）を渡すと系列ごとにピークを探し、見つかった
    位置にマーカーを付け、各ピークで最も高い位置に物質名を書く（近いものは段積み）。
    peaks_on="top" なら、各ピークで最も上の系列にだけマーカーを付ける。
    y 軸の範囲は kaiseki（matplotlib の自動範囲 = データ + 余白 5%、注釈が収まるよう上端を
    広げる）と同じ値を明示する（Plotly の自動範囲は注釈の文字を含めないため）。
    """
    curves = []
    for t in traces:
        x, y = np.asarray(t["x"], dtype=float), np.asarray(t["y"], dtype=float)
        if normalize_each:
            mx = np.nanmax(y)
            if mx and np.isfinite(mx):
                y = y / mx
        curves.append((x, y))

    auto_colors, used_cmap = assign_colors(len(traces), cmap)
    step = overlay_step(curves, offset, gap)
    n = len(traces)

    fig = new_figure(st, title=title, legend=legend)
    if bottom_up:
        # 凡例は常に図の上→下の並びにする（下積みでは描く順が下→上なので逆順）
        fig["layout"]["legend"]["traceorder"] = "reversed"

    infos: list[dict] = []
    ys_all: list[np.ndarray] = []
    for i, (t, (x, y)) in enumerate(zip(traces, curves)):
        color = css_color(t.get("color")) or auto_colors[i]
        if t.get("offset") is not None:
            off = float(t["offset"])                 # 系列ごとの指定が最優先
        else:
            off = (i if bottom_up else (n - 1 - i)) * step
        found = (find_assignment_peaks(x, y, peaks, tol=peak_tol, prominence=peak_prominence)
                 if peaks else [])
        add_line(fig, x, y + off, t["label"], st, color=color)
        # 各系列の基線（オフセットの位置）を薄い点線で
        add_hline(fig, off, color=color, width=st["line"] * 0.4, dash="dot", opacity=0.4)
        ys_all += [y + off, np.array([off])]
        infos.append({"label": t["label"], "color": color, "offset": off,
                      "n_points": int(len(x)), "peaks": found})

    laid: list[dict] = []
    missed: list[str] = []
    if peaks:
        marker_gap = 0.05 * step
        label_anns = []
        for k, (pos, material, marker, pcolor) in enumerate(peaks):
            hits = [(info["peaks"][k]["x"], info["peaks"][k]["y"] + info["offset"])
                    for info in infos if info["peaks"][k]["found"]]
            if peaks_on == "top" and hits:
                hits = [max(hits, key=lambda h: h[1])]
            if hits:
                tpx, tpy = max(hits, key=lambda h: h[1])
                label_anns.append(dict(x=tpx, y_base=tpy + marker_gap, material=material,
                                       marker=marker, color=pcolor, _hits=hits, _tpy=tpy))
            else:
                missed.append(material)
            if peak_guides:
                add_vline(fig, pos, color=css_color(pcolor), width=st["line"] * 0.6,
                          dash="dot", opacity=0.3)

        laid = layout_peak_annotations(label_anns, y_span=step, step_frac=0.12)
        for ann in laid:
            # 最も高い系列のマーカーは段積み後の位置、他の系列はピークの少し上
            mx = [px for px, _ in ann["_hits"]]
            my = [ann["y_anchor"] if ytop == ann["_tpy"] else ytop + marker_gap
                  for _, ytop in ann["_hits"]]
            color = css_color(ann["color"])
            add_line(fig, mx, my, ann["material"], st, lines=False, markers=True,
                     marker_symbol=marker_symbol(ann["marker"]), color=color,
                     marker_size=st["marker"] * 1.4, showlegend=False)
            add_annotation(fig, ann["x"], ann["y_anchor"], ann["material"], st, color=color,
                           yanchor="bottom", yshift=st["marker"] + 2)
            ys_all.append(np.asarray(my, dtype=float))

    # y 範囲: matplotlib の自動範囲（データ + 余白 5%）→ 注釈が収まるよう上端を広げる
    lo, hi = _nan_extent(ys_all)
    span = (hi - lo) or 1.0
    y_lo, y_hi = lo - 0.05 * span, hi + 0.05 * span
    if laid:
        y_hi = max(y_hi, max(a["y_anchor"] for a in laid) + 0.15 * step)

    default_ylabel = OVERLAY_YLABEL + ("  [each max-normalized]" if normalize_each else "")
    set_axis(fig, "xaxis", st, title=xlabel or XLABEL, range=xlim)
    set_axis(fig, "yaxis", st, title=ylabel or default_ylabel, range=[y_lo, y_hi])

    info = {
        "step": step, "cmap": used_cmap, "traces": infos, "peaks_missed": missed,
        "labels": [{"material": a["material"], "x": a["x"], "y": a["y_anchor"],
                    "stack_level": a["stack_level"]} for a in laid],
        "ylim": [y_lo, y_hi],
    }
    return fig, info
