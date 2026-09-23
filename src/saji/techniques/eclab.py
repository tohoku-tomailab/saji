"""Bio-Logic EC-Lab の ASCII .mpt の知識（mpt-cycle-extractor-webui の index.html を移植）。

想定する形（詳しくは docs/data-formats.md の『EC-Lab ASCII .mpt』）::

    EC-Lab ASCII FILE                     ← 1行目で判定する
    Nb header lines : 58                  ← 先頭30行以内。列名の行 = この行番号（1始まり）
    ...（測定条件。使わない）
    mode<TAB>ox/red<TAB>...<TAB>Ewe/V<TAB><I>/mA<TAB>cycle number<TAB>   ← 列名（末尾に空の列）
    2<TAB>1<TAB>...                       ← データ（タブ区切り）

移植元と同じ判定・計算・書式にしてある（tests/test_mpt_cycle.py で移植元の出力と比べる）:
  - 文字コードは UTF-8 → Shift_JIS（読めない文字は置き換え）の順。
  - 行はタブで区切る。列名は前後の空白を落とし、末尾の空の列名を捨てる。データの値は元の文字列のまま。
  - 数値はカンマ小数も読む（最初のカンマだけ . にする）。
  - E_RHE = E_measured + E(ref vs SHE) + (RT ln10 / F) × pH。値は10桁の一般形式（formatG10）。
  - CSV は全欄をダブルクォートで囲み、改行は CRLF、先頭に BOM。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from ..core.plot import add_line, new_figure, series_color, set_axis

# 気体定数 R [J K^-1 mol^-1] とファラデー定数 F [C mol^-1]
R = 8.31446261815324
F = 96485.33212

# 参照電極のプリセット（25 ℃付近のよく使う値。E vs SHE / V）。値は論文に載せる保証ではない。
REFERENCES: dict[str, float] = {
    "hg-hgo-1m-koh": 0.105,     # Hg/HgO (1 M KOH)
    "ag-agcl-sat-kcl": 0.197,   # Ag/AgCl (sat. KCl)
    "ag-agcl-3m-kcl": 0.210,    # Ag/AgCl (3 M KCl)
    "sce": 0.244,               # SCE
}

SIGNATURE = "EC-Lab ASCII FILE"
CYCLE_COLUMNS = ["cycle number", "cycle"]
POTENTIAL_COLUMNS = ["Ewe/V", "<Ewe>/V"]
RHE_COLUMN = "E_RHE/V"
X_CANDIDATES = [RHE_COLUMN, "Ewe/V", "<Ewe>/V"]
Y_CANDIDATES = ["I/mA", "<I>/mA", "I/A", "<I>/A", "I/µA", "I/μA", "I/uA", "|I|/mA"]
PH_MAX = 14.5
BOM = chr(0xFEFF)   # 出力 CSV の先頭に付ける（Excel で開けるように）

_HEADER_RE = re.compile(r"Nb\s+header\s+lines\s*:\s*(\d+)", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


@dataclass
class Extracted:
    """1ファイル分の抽出結果。"""

    csv: str                       # BOM なし。改行 CRLF
    columns: list[str]             # 出力の列（RHE なら末尾に E_RHE/V）
    points: list[dict[str, float]] = field(default_factory=list)   # 列名 → 数値（読めない欄は NaN）

    @property
    def rows(self) -> int:
        return len(self.points)


# ============================================================ 文字列・数値の補助
def decode(raw: bytes) -> str:
    """UTF-8 → Shift_JIS の順で読む（移植元と同じ。先頭の BOM は落とす）。"""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("cp932", errors="replace")
    return text.removeprefix(BOM)


def parse_loose(text: str | None) -> float:
    """カンマ小数にも対応して数値化する。読めなければ NaN。"""
    if text is None:
        return math.nan
    s = str(text).strip().replace(",", ".", 1)
    if not s or "_" in s:
        return math.nan
    try:
        return float(s)
    except ValueError:
        return math.nan


def js_number(value: float) -> str:
    """JavaScript の String(number) と同じ表記（整数なら小数点を付けない）。"""
    if value == 0:
        return "0"
    if float(value).is_integer() and abs(value) < 1e21:
        return str(int(value))
    return repr(float(value))


def cycle_label(value: float) -> str:
    """ファイル名用のサイクル表記。2 → "2"、1.5 → "1p5"。"""
    if abs(value - round(value)) < 1e-9:
        return str(round(value))
    return js_number(value).replace(".", "p")


def format_g10(value: float) -> str:
    """有効10桁の一般形式（移植元の formatG10。PowerShell の G10 に近い）。"""
    a = abs(value)
    if a != 0 and (a >= 1e10 or a < 1e-4):
        mant, exp = f"{value:.9e}".split("e")
        return f"{mant}e{int(exp)}"
    return js_number(float(f"{value:.10g}"))


def csv_field(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def normalize_col(name: str) -> str:
    return _WS_RE.sub(" ", str(name).strip().lower())


def find_column(columns: list[str], candidates: list[str]) -> int:
    """候補名のいずれかと一致する列の位置（候補の順に探す）。無ければ -1。"""
    for cand in candidates:
        wanted = normalize_col(cand)
        for i, col in enumerate(columns):
            if normalize_col(col) == wanted:
                return i
    return -1


def ph_slope(temp_c: float) -> float:
    """RT ln10 / F [V / pH]。"""
    return R * (temp_c + 273.15) * math.log(10) / F


def base_name(source_name: str) -> str:
    """最後の拡張子を落とした名前（出力名と凡例の既定に使う）。"""
    return re.sub(r"\.[^.]+$", "", source_name)


def output_name(source_name: str, cycle: float, rhe: bool) -> str:
    """<名前>_cycle<N>[_RHE].csv。"""
    return f"{base_name(source_name)}_cycle{cycle_label(cycle)}{'_RHE' if rhe else ''}.csv"


def _unique_sorted(values: list[float]) -> list[float]:
    seen: set[float] = set()
    out = []
    for v in values:
        key = round(v * 1e9) / 1e9
        if key not in seen:
            seen.add(key)
            out.append(v)
    return sorted(out)


# ============================================================ 抽出
def extract(text: str, *, cycle: float, rhe: bool, ph: float | None = None,
            ref_vs_she: float = 0.0, temp_c: float = 25.0) -> Extracted:
    """.mpt の文字列から指定サイクルの行を抜き、必要なら E_RHE 列を足した CSV にする。

    ファイルの形が想定と違うときは ValueError（メッセージは利用者向け）。
    pH・温度の妥当性は呼び出し側で確かめておく。
    """
    lines = re.split(r"\r?\n", text)
    if not lines or not lines[0].lstrip().startswith(SIGNATURE):
        raise ValueError("EC-Lab ASCII .mpt ファイルとして認識できません（1行目が EC-Lab ASCII FILE ではない）")

    header_count = None
    for line in lines[:30]:
        m = _HEADER_RE.search(line)
        if m:
            header_count = int(m.group(1))
            break
    if header_count is None:
        raise ValueError("'Nb header lines' が見つかりません")
    header_index = header_count - 1
    if header_index >= len(lines):
        raise ValueError("ヘッダー行数がファイルの長さを超えています")

    raw_columns = [s.strip() for s in lines[header_index].split("\t")]
    while raw_columns and not raw_columns[-1]:
        raw_columns.pop()
    if not raw_columns:
        raise ValueError("データ列名がありません")
    columns = raw_columns

    cycle_index = find_column(columns, CYCLE_COLUMNS)
    if cycle_index < 0:
        raise ValueError("'cycle number' 列が見つかりません")
    potential_index = -1
    if rhe:
        potential_index = find_column(columns, POTENTIAL_COLUMNS)
        if potential_index < 0:
            raise ValueError("電位列 Ewe/V または <Ewe>/V が見つかりません")

    selected: list[list[str]] = []
    available: list[float] = []
    for i in range(header_index + 1, len(lines)):
        if not lines[i].strip():
            continue
        row = lines[i].split("\t")
        if len(row) <= cycle_index:
            raise ValueError(f"データ{i - header_index}行目の列数が不足しています")
        value = parse_loose(row[cycle_index])
        if not math.isfinite(value):
            raise ValueError(f"データ{i - header_index}行目の cycle number を読めません")
        available.append(value)
        if abs(value - cycle) < 1e-9:
            selected.append(row)
    if not selected:
        exist = ", ".join(js_number(v) for v in _unique_sorted(available))
        raise ValueError(f"サイクル {cycle_label(cycle)} がありません（存在: {exist}）")

    out_columns = columns + ([RHE_COLUMN] if rhe else [])
    ph_term = ph_slope(temp_c) * ph if rhe else math.nan
    csv_lines = [",".join(csv_field(c) for c in out_columns)]
    points: list[dict[str, float]] = []
    for row in selected:
        fields = []
        nums: dict[str, float] = {}
        for c, col in enumerate(columns):
            value = row[c] if c < len(row) else ""
            fields.append(csv_field(value))
            nums[col] = parse_loose(value)
        if rhe:
            measured = parse_loose(row[potential_index])
            if not math.isfinite(measured):
                raise ValueError(f"電位を数値として読めません: {row[potential_index]}")
            e_rhe = measured + ref_vs_she + ph_term
            fields.append(csv_field(format_g10(e_rhe)))
            nums[RHE_COLUMN] = e_rhe
        csv_lines.append(",".join(fields))
        points.append(nums)
    return Extracted(csv="\r\n".join(csv_lines) + "\r\n", columns=out_columns, points=points)


# ============================================================ 図
def pick_column(columns: list[str], wanted: str | None, candidates: list[str], fallback: int) -> str:
    """図の軸に使う列。指定があればそれ（無ければ ValueError）、無ければ候補の順、それも無ければ fallback 番目。"""
    if wanted:
        idx = find_column(columns, [wanted])
        if idx < 0:
            raise ValueError(f"列 {wanted!r} がありません（列: {', '.join(columns)}）")
        return columns[idx]
    idx = find_column(columns, candidates)
    if idx >= 0:
        return columns[idx]
    return columns[min(fallback, len(columns) - 1)]


def axis_label(column: str) -> str:
    """列名から軸名を作る。E_RHE/V → "E / V vs. RHE"、Ewe/V → "E / V"、<I>/mA → "I / mA"。

    EC-Lab の平均値の印 < > は落とす（Plotly が HTML のタグとして扱うため）。
    """
    if column == RHE_COLUMN:
        return "E / V vs. RHE"
    if column in ("Ewe/V", "<Ewe>/V"):
        return "E / V"
    column = column.replace("<", "").replace(">", "")
    name, sep, unit = column.rpartition("/")
    return f"{name} / {unit}" if sep and name else column


def series_xy(points: list[dict[str, float]], x_col: str, y_col: str) -> tuple[list[float], list[float]]:
    """測定順のまま、x と y の両方が数値の点だけを残す（CV の閉ループを保つ）。"""
    xs, ys = [], []
    for p in points:
        x, y = p.get(x_col, math.nan), p.get(y_col, math.nan)
        if math.isfinite(x) and math.isfinite(y):
            xs.append(x)
            ys.append(y)
    return xs, ys


def cv_figure(series: list[dict], st: dict, *, x_col: str, y_col: str, title: str | None = None,
              xlabel: str | None = None, ylabel: str | None = None, xlim=None, ylim=None,
              legend: str = "inside") -> dict:
    """series: [{label, x, y, color}] を1つの軸に重ねた図。"""
    fig = new_figure(st, title=title, legend=legend)
    set_axis(fig, "xaxis", st, title=xlabel or axis_label(x_col), range=xlim)
    set_axis(fig, "yaxis", st, title=ylabel or axis_label(y_col), range=ylim)
    for i, s in enumerate(series):
        add_line(fig, s["x"], s["y"], s["label"], st, color=s.get("color") or series_color(i))
    return fig


def figure_name(names: list[str], cycle: float, rhe: bool) -> str:
    """図の名前。1本ならその CSV の名前、複数なら CV_cycle<N>[_RHE]_overlay。"""
    if len(names) == 1:
        return PurePosixPath(names[0]).stem
    return f"CV_cycle{cycle_label(cycle)}{'_RHE' if rhe else ''}_overlay"
