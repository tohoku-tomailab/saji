"""表形式データの頑健な読み込み（kaiseki-tool の common/tableio を bytes/文字列入力に移植）。

想定する崩れ方:
  - 文字コードがバラバラ（測定装置は CP932 が多い）
  - 必要な列が無い / 列順が入れ替わっている
  - データ本体の前にヘッダ（測定条件など）が付いている
  - 末尾に空列（``,,`` 由来）が付く

方針は「列名から列番を判断する」。論理名 → 別名リストで柔軟に対応する。
run() はファイルシステムに触れないので、ここの関数はすべて bytes か文字列を受け取る。
"""

from __future__ import annotations

import codecs
import csv
import io
import re
import unicodedata
from typing import Iterable, Mapping, Sequence

# 装置出力で頻出する文字コードを上から順に試す。
ENCODINGS = ["cp932", "utf-8-sig", "utf-8", "latin-1"]

_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"),
)


# ============================================================ 文字コード
def decode_text(raw: bytes) -> str:
    """複数の文字コードを試して文字列にする。全滅時は cp932 で置換読み。

    BOM があればそれを最優先で信じる（BOM 付き UTF-8 は cp932 でも「復号できて
    しまう」ため、先頭列名が化けて列名解決に失敗する。Excel 経由のCSVで実際に起きた）。
    改行は universal newlines と同じく \\n にそろえる。
    """
    text = None
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            try:
                text = raw.decode(enc)
            except UnicodeDecodeError:
                pass
            break
    if text is None:
        for enc in ENCODINGS:
            try:
                text = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
    if text is None:
        text = raw.decode("cp932", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


# ============================================================ 列名の正規化・解決
def normalize_name(name: str) -> str:
    """列名比較用の正規化: 全半角統一・小文字化・記号/空白除去。"""
    s = unicodedata.normalize("NFKC", str(name)).strip().lower()
    return re.sub(r"[\s_\-/\\().]+", "", s)


def resolve_columns(
    header: Sequence[str],
    wanted: Mapping[str, Sequence[str]],
    *,
    required: Iterable[str] = (),
) -> dict[str, int]:
    """ヘッダ行から「論理名 -> 実際の列番号」を解決する。

    wanted は {論理名: [別名候補, ...]}。論理名自身も候補に含める。
    required に挙げた論理名が見つからなければ ValueError。
    見つからなかった論理名はキーごと省かれる。
    """
    norm_header = [normalize_name(h) for h in header]
    resolved: dict[str, int] = {}
    for logical, aliases in wanted.items():
        for cand in [logical, *aliases]:
            nc = normalize_name(cand)
            if nc in norm_header:
                resolved[logical] = norm_header.index(nc)
                break
    missing = [k for k in required if k not in resolved]
    if missing:
        raise ValueError(f"必要な列が見つかりません: {missing} / 実際のヘッダ: {list(header)}")
    return resolved


# ============================================================ ヘッダ行の探索
def split_row(line: str, delimiter: str = ",") -> list[str]:
    """1行をCSVとして分割する（引用符付きセルも正しく扱う）。"""
    return next(csv.reader([line], delimiter=delimiter), [])


def find_header_row(
    text_or_lines: str | Sequence[str],
    must_contain: Sequence[str],
    *,
    delimiter: str = ",",
    max_scan: int = 200,
) -> int:
    """``must_contain`` の全列名を含む行（ヘッダ行）の行番号を返す。見つからなければ ValueError。"""
    lines = text_or_lines.splitlines() if isinstance(text_or_lines, str) else list(text_or_lines)
    targets = [normalize_name(c) for c in must_contain]
    for i, line in enumerate(lines[:max_scan]):
        cells = [normalize_name(c) for c in split_row(line, delimiter)]
        if all(t in cells for t in targets):
            return i
    raise ValueError(
        f"ヘッダ行が見つかりません（{list(must_contain)} を含む行）。先頭 {max_scan} 行を走査。"
    )


# ============================================================ 名前付きテーブル
def load_named_table(
    text: str,
    wanted: Mapping[str, Sequence[str]],
    *,
    required: Iterable[str] = (),
    header_hint: Sequence[str] | None = None,
    delimiter: str = ",",
    rename: bool = True,
):
    """崩れたCSVを頑健に読み、列名を論理名へそろえた DataFrame を返す。

    header_hint（必ず含まれる列名）を渡すとヘッダ行を自動探索し、その手前の
    測定条件ヘッダを読み飛ばす。省略時は先頭行をヘッダとみなす。
    wanted で論理名に対応づけた列だけを、wanted の順で取り出す。
    """
    import pandas as pd

    skip = find_header_row(text, header_hint, delimiter=delimiter) if header_hint else 0
    df = pd.read_csv(io.StringIO(text), delimiter=delimiter, skiprows=skip, engine="python")
    df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed")]]
    df = df.dropna(axis=1, how="all")

    colmap = resolve_columns(list(df.columns), wanted, required=required)
    ordered = [name for name in wanted if name in colmap]
    out = df.iloc[:, [colmap[name] for name in ordered]].copy()
    if rename:
        out.columns = ordered
    return out


# ============================================================ 数値2列（信号）
_NUM = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")


def load_numeric_pairs(text: str):
    """「数値2つだけの行」を全て拾って (x, y) の numpy 配列にする。

    SmartLab .TXT のようにヘッダ行数が可変でも、データ行だけを追従して抜き出せる。
    """
    import numpy as np

    xs, ys = [], []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and _NUM.match(parts[0]) and _NUM.match(parts[1]):
            xs.append(float(parts[0]))
            ys.append(float(parts[1]))
    if not xs:
        raise ValueError("数値2列のデータが見つかりません")
    return np.asarray(xs), np.asarray(ys)


def load_xy_text(text: str):
    """2列テキスト(x, y)を読む。'#' コメント・空白/タブ区切りに対応（np.loadtxt 相当）。"""
    import numpy as np

    data = np.loadtxt(io.StringIO(text))
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError("2列データとして読めません")
    return data[:, 0], data[:, 1]
