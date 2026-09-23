"""電気化学測定（ポテンショスタット出力CSV）の知識（kaiseki-tool の echem/parse.py・metrics.py を移植）。

想定する形（北斗電工 HZ 系などの《...》区切りCSV。詳しくは docs/data-formats.md）::

    《ファイル情報》
    ,測定項目情報,0x0506,CP ｸﾛﾉﾎﾟﾃﾝｼｮﾒﾄﾘ      ← 測定種はここで分かる
    《測定情報》
    ,面積,1.000000,cm2
    《測定条件》《PGS設定》                      ← 条件（解析には使わない）
    《測定フェイズヘッダ》
    ,フェイズ情報,0x0601,自然電位測定           ← フェイズが順に並ぶ
    ,サイクル番号,1
    《サイクル情報》 開始時間/終了時間
    《測定サンプリングヘッダ》 データ数/データ項目数
    《測定データ》
    ,1 時間t,2 電位E,3 電流I,4 WE/CE,           ← B列からの表（先頭セルが空）
    ,1.000000e+000,-7.658742e-003,...
    《測定フェイズヘッダ》
    ,フェイズ情報,0x0600,本測定                 ← ふつう欲しいのはこれ
    ...
    《解析データヘッダ》

崩れ方への備え:
  - 文字コードは装置依存（CP932 が多い）→ core.tableio.decode_text で自動判定。
  - 表の開始列は「ヘッダ行の最初の非空セル」から決める（B列決め打ちにしない）。
  - ヘッダ末尾の余分なカンマ由来の空列を捨て、データ行はヘッダ長にそろえる。
  - CP の ``種別``（第1電流/第2電流）のような非数値列は文字列のまま残す。
  - 本測定は複数サイクルあり得るので、フェイズは常にリストで扱う。

数値指標:
  - **平均電位**（CP 等）: 本測定の ``電位E`` の平均。
  - **溶液抵抗**（IMP 等）: ``Im Z`` の符号が変わる隣接2点の ``Re Z`` から求める。

測定種は《ファイル情報》の ``測定項目情報`` コード（0x0506=CP / 0x051C=IMP）で判断し、
未知のコードなら列構成から推定する（Re Z/Im Z があればインピーダンス、電位E だけなら
定電流/定電位系）。装置・機種でコードは増えるので、**コード表は当てにしすぎない**。

列は名前で解決する（列順・列の有無は測定条件で変わる）。装置の列名には項目番号が
付く（``17 Re Z``）ので、strip_item_number で落としてから解決する。

ファイルシステムには触れない（入力は bytes / 文字列、出力は bytes）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

from ..core.plot import add_line, add_vline, new_figure, set_axis
from ..core.tableio import decode_text, resolve_columns, split_row

# ============================================================ 定数
SECTION_RE = re.compile(r"^[,\s]*《(.+?)》")

SEC_FILE_INFO = "ファイル情報"
SEC_MEASURE_INFO = "測定情報"
SEC_PHASE_HEADER = "測定フェイズヘッダ"
SEC_CYCLE_INFO = "サイクル情報"
SEC_SAMPLING_HEADER = "測定サンプリングヘッダ"
SEC_DATA = "測定データ"

KEY_ITEM = "測定項目情報"
KEY_PHASE = "フェイズ情報"
KEY_CYCLE = "サイクル番号"
KEY_POINTS = "測定点数"
KEY_START = "開始時間"
KEY_END = "終了時間"

MAIN_PHASE_CODE = "0x0600"
MAIN_PHASE_NAME = "本測定"

#: 列名の先頭に付く項目番号（例 ``17 Re Z`` の ``17``）
ITEM_NUMBER_RE = re.compile(r"^\s*\d+\s+")

#: 測定項目コード -> 短い測定種名（分かっているものだけ。未知は列から推定する）
MEASUREMENT_ITEMS = {
    "0x0506": "CP",
    "0x051c": "IMP",
}

KIND_CP = "CP"
KIND_IMP = "IMP"

#: 論理名 -> 別名候補（項目番号を落とした列名と照合する）
DATA_COLUMNS: dict[str, list[str]] = {
    "time": ["時間t", "時間", "t", "time"],
    "potential": ["電位E", "電位", "E", "potential", "Ewe"],
    "current": ["電流I", "電流", "I", "current"],
    "we_ce": ["WE/CE"],
    "rest_potential": ["自然電位"],
    "freq": ["周波数f", "周波数", "f", "frequency", "freq"],
    "re_z": ["Re Z", "ReZ", "Z'", "Zre", "Z re"],
    "im_z": ["Im Z", "ImZ", "Z''", "Zim", "Z im"],
    "abs_z": ["|Z|", "absZ"],
    "phase_angle": ["位相Φ", "位相", "phase"],
    "kind": ["種別"],
}

#: ``rename=True`` のときの 論理名 -> ASCII 列名
ASCII_NAMES = {
    "time": "time_s", "potential": "E_V", "current": "I_A", "we_ce": "WE_CE_V",
    "rest_potential": "rest_E_V", "freq": "freq_Hz", "re_z": "ReZ_ohm",
    "im_z": "ImZ_ohm", "abs_z": "absZ_ohm", "phase_angle": "phase_deg",
    "kind": "kind",
}

#: 算出する指標の選び方
METRIC_MODES = ("auto", "potential", "resistance", "all", "none")
#: 溶液抵抗の求め方
RS_METHODS = ("mean", "interp")


def strip_item_number(name: str) -> str:
    """列名の先頭の項目番号を落とす（``17 Re Z`` -> ``Re Z``）。

    装置は列名に通し番号を付けるが、番号は機種・設定で変わるので
    列名解決の前に落としておく（解決自体は core.tableio.resolve_columns）。
    """
    return ITEM_NUMBER_RE.sub("", str(name)).strip()


def normalize_code(code: str | None) -> str | None:
    """フェイズ/測定項目コードを ``0x0600`` の形にそろえる。"""
    if code is None:
        return None
    s = str(code).strip().lower()
    if not s:
        return None
    if s.startswith("0x"):
        return "0x" + s[2:].zfill(4)
    return s


# ============================================================ データ構造
@dataclass
class Phase:
    """1つの測定フェイズ（自然電位測定・初期電位保持・本測定 …）。"""

    code: str | None
    name: str | None
    cycle: int | None
    n_points: int | None
    start_time: str | None
    end_time: str | None
    df: pd.DataFrame

    @property
    def is_main(self) -> bool:
        """本測定フェイズか（コード一致、または名前に「本測定」を含む）。"""
        if self.code == MAIN_PHASE_CODE:
            return True
        return bool(self.name and MAIN_PHASE_NAME in self.name)

    @property
    def label(self) -> str:
        """ログ表示用の短い名前。"""
        parts = [p for p in (self.code, self.name) if p]
        head = " ".join(parts) if parts else "(無名フェイズ)"
        return f"{head} / サイクル{self.cycle}" if self.cycle is not None else head


@dataclass
class EchemFile:
    """1ファイル分の解析結果。name はファイル名だけ（フォルダは含めない）。"""

    name: str
    item_code: str | None = None
    item_name: str | None = None
    info: dict[str, list[str]] = field(default_factory=dict)
    phases: list[Phase] = field(default_factory=list)

    # -------------------------------------------------- フェイズの選択
    def main_phases(self) -> list[Phase]:
        """本測定フェイズを出現順に返す。"""
        return [p for p in self.phases if p.is_main]

    def select_phases(self, phase: str | None = None,
                      cycle: int | str | None = None) -> list[Phase]:
        """フェイズを選ぶ。

        Parameters
        ----------
        phase : ``None``/``"main"`` で本測定、``"all"`` で全部、
                ``"0x0601"`` のコード、または名前の部分一致（例 ``"自然電位"``）。
        cycle : サイクル番号。``None``/``"all"`` で全サイクル。
        """
        key = (phase or "main").strip()
        if key.lower() in ("main", "本測定", MAIN_PHASE_CODE):
            picked = self.main_phases()
        elif key.lower() == "all":
            picked = list(self.phases)
        else:
            code = normalize_code(key)
            picked = [p for p in self.phases
                      if p.code == code or (p.name and key in p.name)]
        if cycle is not None and str(cycle).lower() != "all":
            want = int(cycle)
            picked = [p for p in picked if p.cycle == want]
        return picked

    # -------------------------------------------------- 測定情報
    def info_value(self, key: str, index: int = 0) -> str | None:
        """《測定情報》の値を取り出す（無ければ None）。"""
        vals = self.info.get(key) or []
        return vals[index] if len(vals) > index and vals[index] != "" else None

    def info_float(self, key: str, index: int = 0) -> float | None:
        """《測定情報》の値を float で取り出す（数値でなければ None）。"""
        val = self.info_value(key, index)
        try:
            return float(val) if val is not None else None
        except ValueError:
            return None

    def describe_phases(self) -> str:
        """含まれるフェイズの一覧（エラーメッセージ用）。"""
        if not self.phases:
            return "（フェイズなし）"
        return " / ".join(f"{p.label}: {len(p.df)}点" for p in self.phases)


# ============================================================ セクション分割
def split_sections(text: str) -> list[tuple[str, list[list[str]]]]:
    """テキストを ``[(セクション名, 行(セルのリスト)のリスト), ...]`` に分割する。

    最初の《...》より前の行は無視する（通常は存在しない）。
    """
    sections: list[tuple[str, list[list[str]]]] = []
    current: list[list[str]] | None = None
    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            current = []
            sections.append((m.group(1).strip(), current))
            continue
        if current is None:
            continue
        if line.strip() == "":
            continue
        current.append(split_row(line))
    return sections


def rows_to_dict(rows: Sequence[Sequence[str]]) -> dict[str, list[str]]:
    """``,キー,値1,値2`` 形式の行群を ``{キー: [値, ...]}`` にする。"""
    out: dict[str, list[str]] = {}
    for row in rows:
        cells = [c.strip() for c in row]
        idx = next((i for i, c in enumerate(cells) if c != ""), None)
        if idx is None:
            continue
        key = cells[idx]
        values = cells[idx + 1:]
        while values and values[-1] == "":
            values.pop()
        out.setdefault(key, values)
    return out


# ============================================================ 表の切り出し
def rows_to_frame(rows: Sequence[Sequence[str]]) -> pd.DataFrame:
    """《測定データ》の行群を DataFrame にする。

    先頭行をヘッダとみなし、「最初の非空セル」を表の開始列とする。末尾の空列は捨て、
    データ行はヘッダ長にそろえる（足りなければ空文字で埋める）。数値化できる列は
    数値に、できない列（``種別`` など）は文字列のまま残す。
    """
    if not rows:
        return pd.DataFrame()
    header = [c.strip() for c in rows[0]]
    start = next((i for i, c in enumerate(header) if c != ""), None)
    if start is None:
        return pd.DataFrame()
    names = header[start:]
    while names and names[-1] == "":
        names.pop()
    if not names:
        return pd.DataFrame()

    records: list[list[str]] = []
    for row in rows[1:]:
        cells = [c.strip() for c in row][start:start + len(names)]
        if all(c == "" for c in cells):
            continue
        cells += [""] * (len(names) - len(cells))
        records.append(cells)

    df = pd.DataFrame(records, columns=names)
    for col in df.columns:
        converted = pd.to_numeric(df[col], errors="coerce")
        # 1つでも数値になれば数値列とみなす（空セルは NaN のまま）
        if converted.notna().any():
            df[col] = converted
    return df


# ============================================================ ファイル解析
def parse_text(text: str, name: str = "") -> EchemFile:
    """ポテンショスタットCSVの文字列を解析して :class:`EchemFile` を返す。"""
    sections = split_sections(text)
    out = EchemFile(name=name)

    pending: dict[str, object] = {}
    for sec, rows in sections:
        if sec == SEC_FILE_INFO:
            info = rows_to_dict(rows)
            item = info.get(KEY_ITEM) or []
            out.item_code = normalize_code(item[0]) if len(item) > 0 else None
            out.item_name = item[1] if len(item) > 1 else None
        elif sec == SEC_MEASURE_INFO:
            out.info.update(rows_to_dict(rows))
        elif sec == SEC_PHASE_HEADER:
            head = rows_to_dict(rows)
            ph = head.get(KEY_PHASE) or []
            pending = {
                "code": normalize_code(ph[0]) if len(ph) > 0 else None,
                "name": ph[1] if len(ph) > 1 else None,
                "cycle": _as_int(head.get(KEY_CYCLE)),
                "n_points": _as_int(head.get(KEY_POINTS)),
            }
        elif sec == SEC_CYCLE_INFO:
            times = rows_to_dict(rows)
            pending["start_time"] = _first(times.get(KEY_START))
            pending["end_time"] = _first(times.get(KEY_END))
        elif sec == SEC_DATA:
            df = rows_to_frame(rows)
            out.phases.append(Phase(
                code=pending.get("code"),          # type: ignore[arg-type]
                name=pending.get("name"),          # type: ignore[arg-type]
                cycle=pending.get("cycle"),        # type: ignore[arg-type]
                n_points=pending.get("n_points"),  # type: ignore[arg-type]
                start_time=pending.get("start_time"),  # type: ignore[arg-type]
                end_time=pending.get("end_time"),      # type: ignore[arg-type]
                df=df,
            ))
            pending = {}
    return out


def parse_bytes(data: bytes, name: str = "") -> EchemFile:
    """ポテンショスタットCSVの内容（bytes）を解析する。文字コードは自動判定。"""
    return parse_text(decode_text(data), name)


def _first(values: Sequence[str] | None) -> str | None:
    return values[0] if values else None


def _as_int(values: Sequence[str] | None) -> int | None:
    val = _first(values)
    try:
        return int(float(val)) if val not in (None, "") else None
    except ValueError:
        return None


# ============================================================ CSV の書き出し
def phase_tag(phase: Phase, index: int, multiple: bool) -> str:
    """出力ファイル名に付ける識別子（``main`` / ``main_cycle1`` / ``0601_cycle1`` …）。"""
    tag = "main" if phase.is_main else (phase.code or f"phase{index}").replace("0x", "")
    if not multiple:
        return tag
    return f"{tag}_cycle{phase.cycle}" if phase.cycle is not None else f"{tag}_{index}"


def phase_csv(phase: Phase, *, rename: bool = False, encoding: str = "utf-8-sig") -> bytes:
    """フェイズの表をCSVの bytes にする。

    既定は装置の列名（``1 時間t`` など）をそのまま残す。``rename=True`` で
    ASCII の論理名（``time_s`` / ``E_V`` …）に付け替える。
    Excel で開けるよう既定の文字コードは utf-8-sig。改行は LF。
    """
    df = rename_columns(phase.df) if rename else phase.df
    return df.to_csv(index=False, lineterminator="\n").encode(encoding)


def rename_columns(df: pd.DataFrame) -> pd.DataFrame:
    """既知の列を ASCII 名に付け替える（未知の列は項目番号だけ落とす）。"""
    colmap = resolve_data_columns(df)
    inv = {idx: ASCII_NAMES[name] for name, idx in colmap.items()
           if name in ASCII_NAMES}
    out = df.copy()
    out.columns = [inv.get(i, strip_item_number(c)) for i, c in enumerate(df.columns)]
    return out


# ============================================================ 列の解決・測定種
def resolve_data_columns(df: pd.DataFrame) -> dict[str, int]:
    """測定データの列を ``{論理名: 列番号}`` に解決する。"""
    header = [strip_item_number(c) for c in df.columns]
    return resolve_columns(header, DATA_COLUMNS)


def column_series(df: pd.DataFrame, logical: str,
                  colmap: dict[str, int] | None = None) -> pd.Series | None:
    """論理名で列を取り出す（無ければ None）。"""
    colmap = colmap if colmap is not None else resolve_data_columns(df)
    if logical not in colmap:
        return None
    return df.iloc[:, colmap[logical]]


def detect_kind(file: EchemFile, df: pd.DataFrame | None = None) -> str | None:
    """測定種（``CP`` / ``IMP`` …）を判定する。コード優先、無ければ列から推定。"""
    if file.item_code and file.item_code in MEASUREMENT_ITEMS:
        return MEASUREMENT_ITEMS[file.item_code]
    if df is None:
        mains = file.main_phases()
        df = mains[0].df if mains else None
    if df is None or df.empty:
        return None
    colmap = resolve_data_columns(df)
    if "re_z" in colmap and "im_z" in colmap:
        return KIND_IMP
    if "potential" in colmap:
        return KIND_CP
    return None


# ============================================================ 平均電位
@dataclass
class PotentialStats:
    """平均電位の集計結果。"""

    mean: float
    std: float
    n: int
    min: float
    max: float
    time_range: tuple[float | None, float | None] | None = None
    by_kind: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "average_potential_V": self.mean,
            "potential_std_V": self.std,
            "potential_min_V": self.min,
            "potential_max_V": self.max,
            "potential_n": self.n,
        }
        if self.time_range:
            out["potential_time_range"] = list(self.time_range)
        if self.by_kind:
            out["average_potential_by_kind_V"] = dict(self.by_kind)
        return out


def average_potential(df: pd.DataFrame, *,
                      time_range: Sequence[float | None] | None = None
                      ) -> PotentialStats:
    """``電位E`` の平均・ばらつきを返す。

    Parameters
    ----------
    time_range : ``(lo, hi)``。``時間t`` 列でこの範囲に絞ってから平均する。
                 片側だけ指定するときは他方を ``None``。既定（None）は本測定の全体。

    ``種別``（第1電流/第2電流 など）の列があれば種別ごとの平均も併記する
    （設定電流が途中で変わる測定で、全体平均だけ見て取り違えないように）。
    """
    colmap = resolve_data_columns(df)
    if "potential" not in colmap:
        raise ValueError(
            f"電位の列が見つかりません（列: {[str(c) for c in df.columns]}）")

    sub = df
    used_range: tuple[float | None, float | None] | None = None
    if time_range is not None and any(v is not None for v in time_range):
        t = column_series(df, "time", colmap)
        if t is None:
            raise ValueError("時間の列が無いので avg_range は使えません")
        lo, hi = (time_range[0], time_range[1])
        mask = pd.Series(True, index=df.index)
        if lo is not None:
            mask &= t >= lo
        if hi is not None:
            mask &= t <= hi
        sub = df[mask]
        used_range = (lo, hi)
        if sub.empty:
            raise ValueError(f"指定した時間範囲にデータがありません: {lo}〜{hi}")

    e = pd.to_numeric(sub.iloc[:, colmap["potential"]], errors="coerce").dropna()
    if e.empty:
        raise ValueError("電位の数値データがありません")

    by_kind: dict[str, float] = {}
    if "kind" in colmap:
        kinds = sub.iloc[:, colmap["kind"]].astype(str)
        vals = pd.to_numeric(sub.iloc[:, colmap["potential"]], errors="coerce")
        grouped = vals.groupby(kinds).mean().dropna()
        if len(grouped) > 1:
            by_kind = {str(k): float(v) for k, v in grouped.items()}

    return PotentialStats(
        mean=float(e.mean()),
        std=float(e.std(ddof=0)),
        n=int(e.size),
        min=float(e.min()),
        max=float(e.max()),
        time_range=used_range,
        by_kind=by_kind,
    )


# ============================================================ 溶液抵抗
@dataclass
class ResistanceResult:
    """溶液抵抗（Im Z の符号反転点）の算出結果。"""

    resistance: float
    method: str
    crossing_index: int
    n_crossings: int
    freq_before: float | None
    freq_after: float | None
    re_before: float
    re_after: float
    im_before: float
    im_after: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "solution_resistance_ohm": self.resistance,
            "resistance_method": self.method,
            "crossing_index": self.crossing_index,
            "n_crossings": self.n_crossings,
            "crossing_freq_before_hz": self.freq_before,
            "crossing_freq_after_hz": self.freq_after,
            "crossing_re_z_before_ohm": self.re_before,
            "crossing_re_z_after_ohm": self.re_after,
            "crossing_im_z_before_ohm": self.im_before,
            "crossing_im_z_after_ohm": self.im_after,
        }


def find_im_z_crossings(im: np.ndarray) -> list[tuple[int, int]]:
    """``Im Z`` の符号が変わる隣接ペア ``(i, i+1)`` を出現順に返す。

    NaN は飛ばして「有限値どうしの隣接」で見る。ちょうど 0 を跨ぐ場合も拾う。
    """
    idx = np.flatnonzero(np.isfinite(im))
    out: list[tuple[int, int]] = []
    for a, b in zip(idx[:-1], idx[1:]):
        ia, ib = float(im[a]), float(im[b])
        if ia == 0.0 and ib == 0.0:
            continue
        if ia * ib <= 0.0:
            out.append((int(a), int(b)))
    return out


def check_crossing(crossing: int | str) -> None:
    """rs_crossing の書式（first / last / 整数）を確かめる。誤りなら ValueError。"""
    key = str(crossing).strip().lower()
    if key in ("first", "last"):
        return
    try:
        int(key)
    except ValueError as exc:
        raise ValueError(f"未知の crossing 指定: {crossing}（first/last/番号）") from exc


def solution_resistance(df: pd.DataFrame, *, method: str = "mean",
                        crossing: int | str = "first") -> ResistanceResult:
    """``Im Z`` の符号反転点から溶液抵抗を求める。

    Parameters
    ----------
    method   : ``mean``（既定・前後2点の Re Z の平均）/ ``interp``（Im Z=0 への線形内挿）
    crossing : ``first``（既定）/ ``last`` / 0始まりの番号（負なら後ろから）。

    交差はふつう複数見つかる（低周波側はノイズで符号が揺れる）。物理的に意味が
    あるのは**高周波側の最初の交差**なので、ファイル順（高周波→低周波）で最初の
    ものを既定にしている。
    """
    if method not in RS_METHODS:
        raise ValueError(f"未知の method: {method}（{'/'.join(RS_METHODS)}）")
    colmap = resolve_data_columns(df)
    missing = [k for k in ("re_z", "im_z") if k not in colmap]
    if missing:
        raise ValueError(
            f"インピーダンスの列が見つかりません: {missing} "
            f"（列: {[str(c) for c in df.columns]}）")

    re_ = pd.to_numeric(df.iloc[:, colmap["re_z"]], errors="coerce").to_numpy(float)
    im = pd.to_numeric(df.iloc[:, colmap["im_z"]], errors="coerce").to_numpy(float)
    freq_s = column_series(df, "freq", colmap)
    freq = (pd.to_numeric(freq_s, errors="coerce").to_numpy(float)
            if freq_s is not None else None)

    crossings = find_im_z_crossings(im)
    if not crossings:
        raise ValueError("Im Z の符号が変わる点が見つかりません（溶液抵抗を出せません）")

    key = str(crossing).strip().lower()
    if key == "first":
        pos = 0
    elif key == "last":
        pos = len(crossings) - 1
    else:
        try:
            pos = int(key)
        except ValueError as exc:
            raise ValueError(
                f"未知の crossing 指定: {crossing}（first/last/番号）") from exc
        if not -len(crossings) <= pos < len(crossings):
            raise ValueError(
                f"crossing={pos} は範囲外です（交差は {len(crossings)} 個）")
        pos %= len(crossings)

    a, b = crossings[pos]
    re_a, re_b, im_a, im_b = re_[a], re_[b], im[a], im[b]
    if method == "interp" and im_b != im_a:
        value = re_a + (re_b - re_a) * (0.0 - im_a) / (im_b - im_a)
    else:
        value = (re_a + re_b) / 2.0

    return ResistanceResult(
        resistance=float(value),
        method=method,
        crossing_index=pos,
        n_crossings=len(crossings),
        freq_before=float(freq[a]) if freq is not None and np.isfinite(freq[a]) else None,
        freq_after=float(freq[b]) if freq is not None and np.isfinite(freq[b]) else None,
        re_before=float(re_a), re_after=float(re_b),
        im_before=float(im_a), im_after=float(im_b),
    )


# ============================================================ まとめ
def summarize_phase(file: EchemFile, phase: Phase, *,
                    metrics: str = "auto",
                    time_range: Sequence[float | None] | None = None,
                    rs_method: str = "mean",
                    rs_crossing: int | str = "first") -> dict[str, Any]:
    """1フェイズ分の指標をまとめた dict を返す（機械可読・ASCIIキー）。

    kaiseki-tool にあった ``path``（フルパス）キーは持たない（出力にパスを残さないため）。

    Parameters
    ----------
    metrics : ``auto``（測定種から選ぶ）/ ``potential`` / ``resistance`` / ``all``。
              算出できないものは ``*_error`` キーに理由を入れて、処理は止めない。
    """
    kind = detect_kind(file, phase.df)
    out: dict[str, Any] = {
        "file": file.name,
        "item_code": file.item_code,
        "item_name": file.item_name,
        "kind": kind,
        "phase_code": phase.code,
        "phase_name": phase.name,
        "cycle": phase.cycle,
        "n_points": int(len(phase.df)),
        "start_time": phase.start_time,
        "end_time": phase.end_time,
    }
    area = file.info_float("面積")
    if area is not None:
        out["area_cm2"] = area
    ref = file.info_value("参照電極")
    if ref:
        out["reference_electrode"] = ref

    want = str(metrics).lower()
    colmap = resolve_data_columns(phase.df)
    do_potential = want in ("all", "potential") or (
        want == "auto" and "potential" in colmap)
    do_resistance = want in ("all", "resistance") or (
        want == "auto" and kind == KIND_IMP) or (
        want == "auto" and {"re_z", "im_z"} <= set(colmap))

    if do_potential:
        try:
            out.update(average_potential(phase.df, time_range=time_range).to_dict())
        except ValueError as exc:
            out["potential_error"] = str(exc)
    if do_resistance:
        try:
            out.update(solution_resistance(
                phase.df, method=rs_method, crossing=rs_crossing).to_dict())
        except ValueError as exc:
            out["resistance_error"] = str(exc)
    return out


def flatten_metrics(record: dict[str, Any]) -> dict[str, Any]:
    """一覧CSV用に、dict/list の値を展開・除去した平坦な dict にする。"""
    flat: dict[str, Any] = {}
    for key, val in record.items():
        if isinstance(val, dict):
            for k2, v2 in val.items():
                flat[f"{key}[{k2}]"] = v2
        elif isinstance(val, (list, tuple)):
            flat[key] = ",".join("" if v is None else str(v) for v in val)
        else:
            flat[key] = val
    return flat


def metrics_csv(records: list[dict[str, Any]]) -> bytes:
    """指標の一覧CSV（flatten_metrics で平坦化。utf-8-sig・改行 LF）。"""
    df = pd.DataFrame([flatten_metrics(r) for r in records])
    return df.to_csv(index=False, lineterminator="\n").encode("utf-8-sig")


def metrics_json(records: list[dict[str, Any]]) -> bytes:
    """指標の JSON（kaiseki-tool の --metrics-out x.json と同じ書式）。"""
    return json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8")


def format_metrics(rec: dict[str, Any]) -> list[str]:
    """指標を人が読む行に整える（ログ用）。警告にすべき内容は含めない（metric_warnings）。"""
    lines: list[str] = []
    if "average_potential_V" in rec:
        lines.append(
            f"平均電位 = {rec['average_potential_V']:.6f} V"
            f"（n={rec['potential_n']}, std={rec['potential_std_V']:.6f},"
            f" min={rec['potential_min_V']:.6f}, max={rec['potential_max_V']:.6f}）")
        rng = rec.get("potential_time_range")
        if rng:
            lo, hi = rng
            lines.append(f"  ※ 時間 {lo if lo is not None else ''}〜"
                         f"{hi if hi is not None else ''} の範囲で平均")
        for kind, val in (rec.get("average_potential_by_kind_V") or {}).items():
            lines.append(f"  ・{kind}: {val:.6f} V")
    if "solution_resistance_ohm" in rec:
        f_hi, f_lo = rec.get("crossing_freq_before_hz"), rec.get("crossing_freq_after_hz")
        where = f"（{f_lo:.4g}〜{f_hi:.4g} Hz の交差" if f_hi and f_lo else "（"
        lines.append(
            f"溶液抵抗 = {rec['solution_resistance_ohm']:.6g} Ω{where}, "
            f"{rec['n_crossings']}個中{rec['crossing_index'] + 1}番目, "
            f"method={rec['resistance_method']}）")
    return lines


def metric_warnings(rec: dict[str, Any]) -> list[str]:
    """指標について利用者に注意を促す文（交差が複数・算出できなかった指標）。"""
    out: list[str] = []
    if "solution_resistance_ohm" in rec and rec["n_crossings"] > 1:
        out.append(f"Im Z の符号反転が {rec['n_crossings']} 個あります"
                   "（低周波側のノイズの可能性。rs_crossing で選べます。"
                   "crossing_freq_* で意図した点か確認してください）")
    for key in ("potential_error", "resistance_error"):
        if key in rec:
            out.append(str(rec[key]))
    return out


# ============================================================ プレビューの図
def preview_figure(phases: Sequence[tuple[str, Phase]], kind: str | None, st: dict, *,
                   title: str | None = None,
                   records: Sequence[dict[str, Any]] = ()) -> dict[str, Any] | None:
    """抽出したフェイズの確認用の図（プレビュー専用）。描けるものが無ければ None。

    IMP は Nyquist（Z' 対 -Z''。溶液抵抗の位置に縦線）、それ以外は電位の時間変化。
    phases は (凡例名, フェイズ) の並び。軸名・凡例は英語（Arial で表示できるように）。
    """
    nyquist = kind == KIND_IMP
    fig = new_figure(st, title=title, legend="inside")
    n = 0
    for name, ph in phases:
        colmap = resolve_data_columns(ph.df)
        keys = ("re_z", "im_z") if nyquist else ("time", "potential")
        if not all(k in colmap for k in keys):
            continue
        x = pd.to_numeric(ph.df.iloc[:, colmap[keys[0]]], errors="coerce").to_numpy(float)
        y = pd.to_numeric(ph.df.iloc[:, colmap[keys[1]]], errors="coerce").to_numpy(float)
        if nyquist:
            add_line(fig, x, -y, name, st, markers=True, width=st["line_thin"])
        else:
            add_line(fig, x, y, name, st)
        n += 1
    if n == 0:
        return None
    if nyquist:
        for rec in records:
            rs = rec.get("solution_resistance_ohm")
            if rs is not None and np.isfinite(rs):
                add_vline(fig, rs, dash="dash")
        set_axis(fig, "xaxis", st, title="Z' (Ω)")
        set_axis(fig, "yaxis", st, title="-Z'' (Ω)")
    else:
        set_axis(fig, "xaxis", st, title="Time (s)")
        set_axis(fig, "yaxis", st, title="Potential (V)")
    return fig
