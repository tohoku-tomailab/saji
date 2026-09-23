"""XPS raw からスペクトルを抽出する（Multipak Exporter の .txt と 装置の .spe の両対応）。

Multipak 出力にはラベル行（例 ``Survey``）に続いてメタ情報とデータ本体が並ぶ:
  ラベル行 +1: エリア番号 / +2: XLabel / +3: YLabel / +4: データ点数 / +5: データ開始
データ本体は ``x,y`` のCSVで、空行でブロックが終わる（メタ情報の行数は書き出し設定で
変わるので ``offset`` で調整する）。

``.spe`` は装置が吐くバイナリで、実測した全領域が入っている（解析は xps.spe）。
書き出し操作を挟まないぶん領域の取りこぼしが起きないので、原則こちらを使うとよい。

処理:
  1. 指定ラベルのブロックを抽出（.spe でラベル未指定なら全領域、テキストなら既定 "Survey"）
  2. 必要なら x（結合エネルギー）を ``energy_shift`` だけ平行移動（チャージ補正）
  3. y を 0-1 に Min-Max 正規化（normalize=False で無効化）
  4. ``<試料名>_<ラベル>.csv``（ヘッダ x,y）にする

試料名は Multipak の命名 ``<日付>_<氏名>.<測定番号>.<試料名>`` の末尾から推定する。
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import PurePosixPath
from typing import Iterable, Sequence

from ...core.tableio import decode_text
from .spe import is_spe, parse_spe

DEFAULT_LABELS = ["Survey"]
LABEL_DATA_OFFSET = 5
CSV_HEADER = ["x", "y"]


# ============================================================ ブロック抽出
def find_label_index(lines: Sequence[str], label: str) -> int | None:
    """ラベルと完全一致（前後空白は無視）する行のインデックスを返す。"""
    for i, line in enumerate(lines):
        if line.strip() == label:
            return i
    return None


def extract_block_by_label(lines: Sequence[str], label: str,
                           offset: int = LABEL_DATA_OFFSET) -> list[str]:
    """ラベル行の offset 行下から空行までを生データ行として抽出する。"""
    label_index = find_label_index(lines, label)
    if label_index is None:
        return []
    start = label_index + offset
    if start >= len(lines):
        return []
    block: list[str] = []
    for line in lines[start:]:
        if line.strip() == "":
            break
        block.append(line.strip())
    return block


def parse_xy_rows(raw_rows: Sequence[str]) -> list[tuple[float, float]]:
    """``x,y`` 形式の行群を (x, y) の float ペアに変換する。"""
    reader = csv.reader(io.StringIO("\n".join(raw_rows)))
    parsed: list[tuple[float, float]] = []
    for idx, row in enumerate(reader, start=1):
        if len(row) < 2:
            raise ValueError(f"列が不足しています。行: {idx}, data={row}")
        try:
            parsed.append((float(row[0]), float(row[1])))
        except ValueError as exc:
            raise ValueError(f"数値変換に失敗しました。行: {idx}, data={row}") from exc
    return parsed


# ============================================================ 正規化・命名
def normalize_minmax(rows: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """y を 0-1 の範囲に Min-Max 正規化する（値幅0なら全て0）。"""
    if not rows:
        return []
    ys = [y for _, y in rows]
    y_min, y_max = min(ys), max(ys)
    y_range = y_max - y_min
    if y_range == 0:
        return [(x, 0.0) for x, _ in rows]
    return [(x, (y - y_min) / y_range) for x, y in rows]


def infer_sample_name(filename: str) -> str:
    """rawファイル名から試料名を推定する（stem をドット区切りした末尾）。

    例: ``20260713_Name.108.sampleX.txt`` -> ``sampleX``
    """
    return PurePosixPath(filename).stem.split(".")[-1]


def squash_label(label: str) -> str:
    """照合・ファイル名用にラベルの空白とアンダースコアを落とす。

    同じ領域を Multipak は ``Cu LMM``、.spe は ``Cu_LMM`` と書くため。
    """
    return re.sub(r"[\s_]+", "", label)


def match_label(label: str, available: Iterable[str]) -> str | None:
    """空白・アンダースコアの違いを無視してラベルを照合し、実際のキーを返す。"""
    want = squash_label(label)
    for name in available:
        if squash_label(name) == want:
            return name
    return None


def default_labels_for(filename: str) -> list[str] | None:
    """ラベル未指定時に何を抜くか。.spe は全領域（None）、テキストは既定ラベル。"""
    return None if is_spe(filename) else list(DEFAULT_LABELS)


def parse_labels(value: str | None) -> list[str] | None:
    """``"Survey,C1s"`` → ``["Survey", "C1s"]``。未指定（None・空）なら None。"""
    if value is None:
        return None
    labels = [v.strip() for v in value.split(",") if v.strip()]
    return labels or None


# ============================================================ ファイル処理
def extract_file(
    filename: str,
    data: bytes,
    *,
    labels: Iterable[str] | None = None,
    offset: int = LABEL_DATA_OFFSET,
    normalize: bool = True,
    energy_shift: float = 0.0,
) -> dict[str, list[tuple[float, float]]]:
    """1ファイルからラベルごとのスペクトルを抽出して dict で返す。

    ``labels=None`` なら .spe は全領域、テキストは既定ラベル（Survey）。
    見つからなかったラベルはキーごと省かれる。テキストのラベルは完全一致で探す
    （空白・アンダースコアを無視した照合は .spe だけ。kaiseki-tool と同じ）。
    """
    if is_spe(filename):
        spectra = parse_spe(data)
        if labels is None:
            wanted = list(spectra)
        else:
            wanted = [name for name in (match_label(v, spectra) for v in labels) if name]
    else:
        lines = decode_text(data).splitlines()
        spectra = {}
        for label in (DEFAULT_LABELS if labels is None else labels):
            raw = extract_block_by_label(lines, label, offset)
            if raw:
                spectra[label] = parse_xy_rows(raw)
        wanted = list(spectra)

    out: dict[str, list[tuple[float, float]]] = {}
    for name in wanted:
        rows = spectra[name]
        if energy_shift:
            rows = [(round(x + energy_shift, 6), y) for x, y in rows]
        out[name] = normalize_minmax(rows) if normalize else rows
    return out


def output_name(filename: str, label: str) -> str:
    """出力ファイル名 ``<試料名>_<ラベル（空白・_ を除く）>.csv``。"""
    return f"{infer_sample_name(filename)}_{squash_label(label)}.csv"


def format_csv(rows: Sequence[tuple[float, float]]) -> str:
    """(x, y) ペア列をヘッダ付きCSV（x,y）の文字列にする。

    kaiseki-tool と同じく csv モジュールの既定（改行 CRLF、数値は repr）で書く。
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_HEADER)
    writer.writerows(rows)
    return buf.getvalue()
