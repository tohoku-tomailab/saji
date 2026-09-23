"""PHI VersaProbe の .spe（バイナリ）から領域ごとのスペクトルを読む。

Multipak で書き出した .txt/.csv と違い、装置が吐いた .spe を直接読む。書き出し操作を
挟まないので「領域を選び忘れて一部しか出ていない」といった取りこぼしが起きない。

構造:
  ``EOFH`` までが ASCII ヘッダ、その後ろがバイナリ部。
  ヘッダの ``SpectralRegDef:`` 行が実測した領域（名前・点数・BE範囲）を順に持つ
  （``SpectralRegDefFull:`` は「定義しただけ」の領域なので使わない）。
  バイナリ部 = 全体ヘッダ(int32×4) + 領域ごとのテーブル(int32×24) + float32 の y 値。
  テーブルからは点数・データのバイト長・バイトオフセットだけを使い、x 軸はヘッダの
  BE 範囲から等間隔で作る（強度は Multipak の書き出しCSVと一致することを確認済み）。
"""

from __future__ import annotations

import re
import struct
from pathlib import PurePosixPath

SPE_SUFFIX = ".spe"
HEADER_END = b"EOFH"
TABLE_START_INTS = 4
ENTRY_INTS = 24
ENTRY_NPOINTS = 5
ENTRY_NBYTES = 19
ENTRY_OFFSET = 20

# SpectralRegDef: <番号> <?> <領域名> <原子番号> <点数> <ステップ> <開始BE> <終了BE> ...
REGION_RE = re.compile(
    r"^SpectralRegDef:\s+\d+\s+\d+\s+(\S+)\s+\d+\s+(\d+)\s+-?[\d.]+\s+(-?[\d.]+)\s+(-?[\d.]+)",
    re.M,
)


def is_spe(filename: str) -> bool:
    """拡張子から .spe かどうかを判定する。"""
    return PurePosixPath(filename).suffix.lower() == SPE_SUFFIX


def split_header(data: bytes) -> tuple[str, bytes]:
    """ASCIIヘッダ文字列とバイナリ部を分ける。"""
    end = data.find(HEADER_END)
    if end < 0:
        raise ValueError(f"{HEADER_END.decode()} が見つかりません（.spe ではない可能性があります）")
    body_start = end + len(HEADER_END)
    while body_start < len(data) and data[body_start] in (0x0D, 0x0A):
        body_start += 1
    return data[:end].decode("latin-1"), data[body_start:]


def parse_regions(header: str) -> list[tuple[str, int, float, float]]:
    """ヘッダから (領域名, 点数, 開始BE, 終了BE) の一覧を実測順で得る。"""
    return [
        (name, int(npts), float(x_start), float(x_end))
        for name, npts, x_start, x_end in REGION_RE.findall(header)
    ]


def parse_spe(data: bytes) -> dict[str, list[tuple[float, float]]]:
    """.spe の内容を読み、領域名 -> [(結合エネルギー, 強度)] の dict を返す。

    x はヘッダの BE 範囲を点数で等分して作る（装置が刻む生の軸。Multipak が
    書き出し時に掛けるチャージ補正は入っていない）。
    """
    header, body = split_header(data)
    regions = parse_regions(header)
    if not regions:
        raise ValueError("SpectralRegDef 行が見つかりません")

    table = struct.unpack(f"<{len(body) // 4}i", body[: len(body) // 4 * 4])
    out: dict[str, list[tuple[float, float]]] = {}
    for i, (name, npts, x_start, x_end) in enumerate(regions):
        base = TABLE_START_INTS + ENTRY_INTS * i
        entry = table[base : base + ENTRY_INTS]
        if len(entry) < ENTRY_INTS:
            raise ValueError(f"領域テーブルが足りません（領域 {name}）")
        n, nbytes, offset = entry[ENTRY_NPOINTS], entry[ENTRY_NBYTES], entry[ENTRY_OFFSET]
        if n != npts or nbytes != n * 4 or offset + nbytes > len(body):
            raise ValueError(
                f"領域 {name} のテーブルがヘッダと矛盾します"
                f"（点数 header={npts} table={n}, bytes={nbytes}, offset={offset}）"
            )
        ys = struct.unpack(f"<{n}f", body[offset : offset + nbytes])
        step = (x_end - x_start) / (n - 1) if n > 1 else 0.0
        out[name] = [(round(x_start + step * k, 6), float(y)) for k, y in enumerate(ys)]
    return out
