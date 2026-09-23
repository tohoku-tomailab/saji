"""CO2RR（CO2 電解還元）の手法知識: ファラデー効率の集計と積み上げ棒グラフ。

読み込み・ラベル付け・集計は kaiseki-tool の co2rr/plot.py と等価に保つ
（集計CSVはバイト単位で一致させる。tests/golden/co2rr-plot/）。
入力形式は docs/data-formats.md の「CO2RR 測定CSV」を参照。

処理の流れ:
  1. 崩れうるCSVを core.tableio で頑健に読み、列名（別名つき）から必要な列を解決する
  2. 各行にラベルを付ける（列そのまま / 正規表現で抽出 / sample_id → ラベルの辞書）
  3. 同じラベルの行をまとめて平均と誤差（std / sem）を出す
  4. 生成物を積み上げた棒グラフ + 第2y軸に電位を描く

図の約束（docs/plotting.md）:
  - 棒は生成物ごとの系列を barmode="stack" で積む。積み上げ順は下→上、凡例は上→下（逆順）。
  - 誤差は各生成物の上端（segment）か、合計の上端（total）に付ける。
  - 電位は右の第2y軸に、オレンジの線＋四角マーカーで描く（誤差つき）。
  - 生成物名は下付き文字を <sub> で書く（H<sub>2</sub> など）。軸名などの既定値は英語。
"""

from __future__ import annotations

import io
import json
import math
import re
from typing import Any, Mapping, Sequence

import numpy as np

from ..core.plot import add_bar, add_line, new_figure, set_axis
from ..core.plot.style import css_color
from ..core.tableio import load_named_table

# 既定の生成物列（kaiseki-tool のサンプルCSVに準拠）。積み上げは下→上の順。
DEFAULT_PRODUCTS = ["H2", "CO", "CH4", "C2H4", "CH3COOH", "1-PrOH", "EtOH", "HCOOH"]

# 生成物名の別名（列名の揺れに対応）。論理名は上の DEFAULT_PRODUCTS。
# 照合は core.tableio.normalize_name で正規化してから行う（大小文字・空白・記号は無視）。
PRODUCT_ALIASES: dict[str, list[str]] = {
    "H2": ["hydrogen", "水素"],
    "CO": ["carbonmonoxide", "一酸化炭素"],
    "CH4": ["methane", "メタン"],
    "C2H4": ["ethylene", "c2h4", "エチレン"],
    "CH3COOH": ["aceticacid", "acetic", "ch3cooh", "酢酸", "aa"],
    "1-PrOH": ["1proh", "npropanol", "propanol", "1プロパノール", "nproh"],
    "EtOH": ["ethanol", "etoh", "エタノール"],
    "HCOOH": ["formicacid", "formic", "hcooh", "ギ酸", "fa"],
}

# 凡例に出す表示名（Plotly の簡易HTML。matplotlib 変換器が mathtext に直す）。
DISPLAY_NAMES: dict[str, str] = {
    "H2": "H<sub>2</sub>",
    "CO": "CO",
    "CH4": "CH<sub>4</sub>",
    "C2H4": "C<sub>2</sub>H<sub>4</sub>",
    "CH3COOH": "CH<sub>3</sub>COOH",
    "1-PrOH": "1-PrOH",
    "EtOH": "EtOH",
    "HCOOH": "HCOOH",
}

# 既定色（kaiseki-tool のサンプル図に合わせたもの）。
DEFAULT_COLORS: dict[str, str] = {
    "H2": "#bfbfbf",       # 灰
    "CO": "#ffd400",       # 黄
    "CH4": "#e8000b",      # 赤
    "C2H4": "#8000ff",     # 紫
    "CH3COOH": "#8b0000",  # 暗赤
    "1-PrOH": "#00008b",   # 濃青
    "EtOH": "#00c000",     # 緑
    "HCOOH": "#00d5ff",    # 水
}

POTENTIAL_COLOR = "#ff7f0e"   # 電位の線（オレンジ）

# 図の既定の文言（フォントは Arial だけなので英語にする）。
YLABEL = "Faradaic efficiency / %"
POTENTIAL_LABEL = "Potential / V"

_LABEL_ALIASES = ["label", "ラベル"]
_GROUP_ALIASES = ["group", "グループ", "群"]
_ID_ALIASES = ["id", "sampleid", "sample", "試料id", "サンプルid"]
_NAME_ALIASES = ["name", "samplename", "試料名", "サンプル名"]
_POTENTIAL_ALIASES = ["potential", "v", "電位", "voltage", "e", "過電圧", "overpotential"]

ERRORS = ("std", "sem", "none")
ERROR_MODES = ("segment", "total", "none")


# ============================================================ 読み込み
def load_co2rr(
    text: str,
    *,
    products: Sequence[str] | None = None,
    id_col: str = "sample_id",
    name_col: str = "sample_name",
    potential_col: str = "potential",
):
    """CO2RR の測定CSV（文字列）を読み、必要な列だけを論理名にそろえた DataFrame を返す。

    戻り値は (df, 実在した生成物名のリスト, ヘッダ行を探索で見つけたか)。
    df の列は wanted の順（id_col, name_col, group, label, 生成物…, potential_col）のうち
    実在したものだけ。それ以外の列は読み捨てる。

    ヘッダ行の探索アンカーは「必ずある生成物列」（products の先頭2つの論理名）に置く。
    見つからなければ先頭行をヘッダとみなして読み直す（前置きの無いCSV・別名の列名用）。
    """
    import pandas as pd

    products = list(products or DEFAULT_PRODUCTS)
    wanted: dict[str, list[str]] = {
        id_col: _ID_ALIASES,
        name_col: _NAME_ALIASES,
        "group": _GROUP_ALIASES,
        "label": _LABEL_ALIASES,
    }
    for p in products:
        wanted[p] = PRODUCT_ALIASES.get(p, [])
    wanted[potential_col] = _POTENTIAL_ALIASES

    hint = products[:2]
    try:
        df = load_named_table(text, wanted, header_hint=hint)
        hinted = True
    except ValueError:
        df = load_named_table(text, wanted, header_hint=None)
        hinted = False

    present = [p for p in products if p in df.columns]
    if not present:
        raise ValueError(f"生成物の列が1つも見つかりません。期待した列: {products}")
    # 数値にする（空欄や数値でない値は NaN。平均では無視される）
    for p in present:
        df[p] = pd.to_numeric(df[p], errors="coerce")
    if potential_col in df.columns:
        df[potential_col] = pd.to_numeric(df[potential_col], errors="coerce")
    return df, present, hinted


# ============================================================ ラベル付け
def label_source(df, *, id_col: str = "sample_id", name_col: str = "sample_name",
                 label_col: str | None = None) -> str:
    """ラベル元にする列名を決める（明示 label_col > group > label > name_col > id_col）。"""
    if label_col and label_col in df.columns:
        return label_col
    if "group" in df.columns and df["group"].notna().any():
        return "group"
    if "label" in df.columns and df["label"].notna().any():
        return "label"
    if name_col in df.columns:
        return name_col
    if id_col in df.columns:
        return id_col
    raise ValueError("ラベル元の列が見つかりません（group / label / name / id のいずれも無い）")


def assign_labels(
    df,
    *,
    id_col: str = "sample_id",
    name_col: str = "sample_name",
    label_col: str | None = None,
    label_map: Mapping[str, str] | None = None,
    label_pattern: str | None = None,
):
    """各行に 'label' 列を付けた DataFrame（コピー）を返す。

    優先順: label_map（{sample_id: ラベル}）> 正規表現 > ラベル元の列（label_source）。
    label_pattern はラベル元の文字列から正規表現で抜き出す（グループがあれば1つ目、
    無ければ一致した全体。一致しなければ元の文字列のまま）。例 r"pH\\d+" で
    "reCupH7fA" → "pH7"。ラベル元が空欄の行はラベルも空（NaN）になり、集計から外れる。
    """
    df = df.copy()
    base = df[label_source(df, id_col=id_col, name_col=name_col, label_col=label_col)].astype(str)

    if label_pattern:
        rx = re.compile(label_pattern)

        def _extract(s: Any) -> Any:
            if not isinstance(s, str):      # 空欄（NaN）はそのまま
                return s
            m = rx.search(s)
            if not m:
                return s
            return m.group(1) if m.groups() else m.group(0)

        base = base.map(_extract)

    labels = base.copy()
    if label_map and id_col in df.columns:
        ids = df[id_col].astype(str)
        labels = ids.map(lambda i: label_map.get(i)).where(lambda s: s.notna(), labels)
    df["label"] = labels.astype(str)
    return df


# ============================================================ 集計
def aggregate(df, products: Sequence[str], *, potential_col: str = "potential",
              error: str = "std", label_order: Sequence[str] | None = None):
    """ラベルごとに平均と誤差を集計した DataFrame（1ラベル1行）を返す。

    列は label, n, <生成物>, <生成物>_err, …, <potential_col>, <potential_col>_err。
    生成物の値がすべて空欄の群は平均 0.0、電位がすべて空欄の群は NaN。
    誤差は error="std"（標準偏差, ddof=1）/ "sem"（標準誤差）/ "none"（0）。
    値が1つ以下のときも 0。行の順は label_order（無い名前は飛ばす）、無ければ初出順。
    """
    import pandas as pd

    if error not in ERRORS:
        raise ValueError(f"error は {'/'.join(ERRORS)}: {error}")
    has_pot = potential_col in df.columns
    order = list(label_order) if label_order else list(dict.fromkeys(df["label"]))

    rows = []
    for lab in order:
        sub = df[df["label"] == lab]
        if sub.empty:
            continue
        rec: dict[str, Any] = {"label": lab, "n": int(len(sub))}
        for p in products:
            vals = sub[p].dropna()
            rec[p] = float(vals.mean()) if len(vals) else 0.0
            rec[f"{p}_err"] = _err(vals, error)
        if has_pot:
            pv = sub[potential_col].dropna()
            rec[potential_col] = float(pv.mean()) if len(pv) else np.nan
            rec[f"{potential_col}_err"] = _err(pv, error)
        rows.append(rec)
    return pd.DataFrame(rows)


def _err(vals, error: str) -> float:
    """群の誤差（値が1つ以下や none のときは 0）。"""
    n = len(vals)
    if error == "none" or n < 2:
        return 0.0
    sd = float(vals.std(ddof=1))
    if error == "sem":
        return sd / np.sqrt(n)
    return sd


# ============================================================ 出力
def format_summary_csv(agg) -> str:
    """集計表の CSV 文字列（kaiseki-tool の save_summary_csv と同じ書式。utf-8-sig で保存する）。"""
    buf = io.StringIO()
    agg.to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue()


def summary_records(agg) -> list[dict[str, Any]]:
    """集計表を JSON にできる dict のリストにする（NaN は None）。"""
    out = []
    for rec in agg.to_dict(orient="records"):
        row: dict[str, Any] = {}
        for k, v in rec.items():
            if hasattr(v, "item"):
                v = v.item()
            if isinstance(v, float) and not math.isfinite(v):
                v = None
            row[str(k)] = v
        out.append(row)
    return out


def parse_name_list(value: Any) -> list[str] | None:
    """"a,b,c" か JSON のリスト '["a", "b"]'（名前にカンマを含むとき）を名前のリストにする。"""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        items = [str(v) for v in value]
    else:
        s = str(value).strip()
        if s.startswith("["):
            loaded = json.loads(s)
            if not isinstance(loaded, list):
                raise ValueError("JSON のリストにしてください")
            items = [str(v) for v in loaded]
        else:
            items = s.split(",")
    items = [v.strip() for v in items if v.strip()]
    return items or None


# ============================================================ 図
def co2rr_figure(
    agg,
    products: Sequence[str],
    st: dict,
    *,
    potential_col: str = "potential",
    colors: Mapping[str, str] | None = None,
    stack_order: Sequence[str] | None = None,
    ylim: Sequence[float | None] | None = None,
    ylim2: Sequence[float | None] | None = None,
    xlabel: str | None = None,
    ylabel: str = YLABEL,
    potential_label: str = POTENTIAL_LABEL,
    title: str | None = None,
    show_potential: bool = True,
    show_values: bool = True,
    min_value_label: float = 3.0,
    error_mode: str = "segment",
    value_fmt: str = "{:.1f}",
    bar_width: float = 0.6,
) -> dict[str, Any]:
    """集計表から、積み上げ棒グラフ（+ 第2y軸に電位）の図を作る。

    error_mode:
      segment … 各生成物の上端にその生成物の誤差
      total   … 積み上げの上端に合計の誤差（各生成物の誤差の二乗和の平方根）。
                 高さ 0 の棒を最上段に積み、その棒の error_y で描く（許可した要素だけで
                 Plotly と matplotlib の両方に同じ位置で出せるため）。
      none    … 誤差を描かない
    min_value_label 未満（%）の区分には数値を書かない。
    """
    if error_mode not in ERROR_MODES:
        raise ValueError(f"error_mode は {'/'.join(ERROR_MODES)}: {error_mode}")
    colors = {**DEFAULT_COLORS, **(colors or {})}
    order = [p for p in (stack_order or products) if p in products]
    labels = [str(v) for v in agg["label"]]
    n = len(labels)
    zeros = np.zeros(n)

    fig = new_figure(st, title=title or None, legend="outside")
    layout = fig["layout"]
    layout["barmode"] = "stack"
    layout["legend"]["traceorder"] = "reversed"   # 積み上げの上の生成物を凡例の上に

    errs_all = []
    for p in order:
        vals = agg[p].to_numpy(dtype=float)
        errs = agg[f"{p}_err"].to_numpy(dtype=float) if f"{p}_err" in agg.columns else zeros
        errs_all.append(errs)
        seg_err = errs if error_mode == "segment" and np.any(errs > 0) else None
        text = None
        if show_values:
            text = [value_fmt.format(v) if v >= min_value_label else "" for v in vals]
        tr = add_bar(fig, labels, vals, DISPLAY_NAMES.get(p, p), color=css_color(colors.get(p)),
                     error=seg_err, width=bar_width, text=text, text_size=st["annotation"])
        tr["hovertemplate"] = "%{x}: %{y:.2f} %<extra>%{fullData.name}</extra>"

    if error_mode == "total" and errs_all:
        total_err = np.sqrt(sum(e ** 2 for e in errs_all))
        if np.any(total_err > 0):
            tr = add_bar(fig, labels, zeros, "Total error", error=total_err, width=bar_width,
                         showlegend=False)
            tr["marker"]["line"]["width"] = 0

    has_pot = potential_col in agg.columns and agg[potential_col].notna().any()
    if has_pot and show_potential:
        pv = agg[potential_col].to_numpy(dtype=float)
        perr = (agg[f"{potential_col}_err"].to_numpy(dtype=float)
                if f"{potential_col}_err" in agg.columns else zeros)
        tr = add_line(fig, labels, pv, potential_label, st, color=POTENTIAL_COLOR, markers=True,
                      marker_symbol="square", yaxis="y2", showlegend=False,
                      error=perr if np.any(perr > 0) else None)
        tr["hovertemplate"] = "%{x}: %{y:.3f} V<extra>%{fullData.name}</extra>"

    set_axis(fig, "xaxis", st, title=xlabel or None, category=True)
    set_axis(fig, "yaxis", st, title=ylabel or None, range=ylim)
    if has_pot and show_potential:
        set_axis(fig, "yaxis2", st, title=potential_label or None, range=ylim2,
                 overlaying="y", side="right")
    return fig
