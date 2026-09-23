"""XPS の合成データ（fixtures）を作るスクリプト。実データは使わない。

    uv run python tests/fixtures/xps/make.py

決定的（乱数は seed 固定）なので、何度実行しても同じファイルになる。作るもの:

  - ``20260101_Synth.1.sampleA.spe`` … PHI .spe（ASCII ヘッダ + int32 テーブル + float32 の y）
  - ``20260101_Synth.2.sampleB.txt`` … Multipak Exporter の .txt（ラベル行の5行下からデータ）
  - ``20260101_Synth.3.sampleC.txt`` … 同上。メタ情報が1行だけの書き出し（offset=2 で読む）
  - ``extracted/*.csv`` … 抽出済みの x,y CSV（xps-plot 用）
  - ``fit/*.csv`` … ピークフィッティング結果 CSV（xps-fit 用。BOM 付き・前置きヘッダ付きを含む）
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent

# .spe のバイナリ部: 全体ヘッダ(int32×4) + 領域ごとのテーブル(int32×24) + float32 の y
TABLE_START_INTS = 4
ENTRY_INTS = 24


def gauss(x, mu, h, w):
    return h * np.exp(-0.5 * ((x - mu) / w) ** 2)


def shirley_like(x, lo, hi, center, width):
    """高結合エネルギー側で持ち上がる段差（Shirley 背景の形をまねたもの）。"""
    return lo + (hi - lo) / (1 + np.exp(np.clip(-(x - center) / width, -50, 50)))


# ============================================================ スペクトルの形
def region_axis(x_start: float, x_end: float, n: int) -> np.ndarray:
    step = (x_end - x_start) / (n - 1)
    return np.array([round(x_start + step * k, 6) for k in range(n)])


def survey(x, rng):
    y = 2000 + 3.0 * x
    for mu, h, w in [(932.7, 9000, 2.0), (952.5, 4500, 2.0), (531.0, 12000, 1.6),
                     (284.8, 5000, 1.4), (568.0, 2500, 3.0), (74.0, 1500, 1.5)]:
        y = y + gauss(x, mu, h, w) + shirley_like(x, 0, h * 0.4, mu, 1.0)
    return y + rng.normal(0, 60, x.size)


def c1s(x, rng):
    y = shirley_like(x, 800, 1300, 285.0, 0.8) + gauss(x, 284.8, 6000, 0.6) + gauss(x, 288.5, 900, 0.7)
    return y + rng.normal(0, 40, x.size)


def o1s(x, rng):
    y = shirley_like(x, 1500, 2600, 531.0, 0.8)
    y = y + gauss(x, 529.8, 9000, 0.55) + gauss(x, 531.3, 4000, 0.7) + gauss(x, 532.8, 1500, 0.8)
    return y + rng.normal(0, 50, x.size)


def cu_lmm(x, rng):
    y = 5000 + 20 * (x - 560) + gauss(x, 568.0, 2500, 1.5) + gauss(x, 570.2, 1200, 1.2)
    return y + rng.normal(0, 30, x.size)


# ============================================================ .spe
def spe_bytes(regions: list[tuple[str, float, float, np.ndarray]]) -> bytes:
    """(名前, 開始BE, 終了BE, y) の一覧から .spe のバイト列を組み立てる。"""
    header = [
        "SOFH",
        "FileDesc: synthetic test data (not a real measurement)",
        "FileType: SPECTRUM",
        "AcqFilename: 20260101_Synth.1.sampleA.spe",
        "InstrumentModel: SYNTHETIC",
        f"NoSpectralReg: {len(regions)}",
    ]
    for i, (name, x0, x1, ys) in enumerate(regions, start=1):
        step = (x1 - x0) / (len(ys) - 1)
        header.append(
            f"SpectralRegDef: {i} 1 {name} 29 {len(ys)} {step:.4f} "
            f"{x0:.4f} {x1:.4f} {x0 - 1:.4f} {x1 + 1:.4f} 1.200000 23.50 AREA"
        )
        # 定義しただけの領域（Full）。抽出では無視されること
        header.append(f"SpectralRegDefFull: {i} 0 Dummy{i} 1 3 -1.0 10.0 0.0 10.0 0.0 0.0 1.0 AREA")
    header += [f"SpectralRegHero: {i} 1" for i in range(1, len(regions) + 1)]
    header.append("EOFH")
    head = ("\r\n".join(header) + "\r\n").encode("latin-1")

    data_start = (TABLE_START_INTS + ENTRY_INTS * len(regions)) * 4
    table = [1, len(regions), 768, 16]
    blobs, offset = [], data_start
    for name, _x0, _x1, ys in regions:
        entry = [0] * ENTRY_INTS
        entry[0] = len(table)
        entry[5] = len(ys)
        entry[19] = len(ys) * 4
        entry[20] = offset
        table += entry
        blobs.append(struct.pack(f"<{len(ys)}f", *ys))
        offset += len(ys) * 4
    body = struct.pack(f"<{len(table)}i", *table) + b"".join(blobs)
    return head + body


def make_spe() -> None:
    rng = np.random.default_rng(11)
    regions = []
    for name, x0, x1, n, fn in [
        ("Su1s", 1100.0, 0.0, 1101, survey),
        ("C1s", 296.0, 280.0, 161, c1s),
        ("O1s", 538.0, 526.0, 121, o1s),
        ("Cu_LMM", 580.0, 560.0, 101, cu_lmm),
    ]:
        x = region_axis(x0, x1, n)
        regions.append((name, x0, x1, np.round(fn(x, rng), 1)))
    (HERE / "20260101_Synth.1.sampleA.spe").write_bytes(spe_bytes(regions))


# ============================================================ Multipak .txt
def multipak_block(label: str, x: np.ndarray, y: np.ndarray, *, meta: list[str]) -> list[str]:
    lines = [label, *meta]
    lines += [f"{a:.4f},{b:.1f}" for a, b in zip(x, y)]
    lines.append("")
    return lines


def make_multipak() -> None:
    rng = np.random.default_rng(12)
    shift = 0.4838      # Multipak が書き出し時に掛けるチャージ補正（全領域一律）
    head = ["SOFH", "InstrumentModel: SYNTHETIC", "Date: 2026/01/01", "SOFE", ""]
    lines = list(head)
    for label, x0, x1, n, fn in [
        ("Survey", 1100.0, 0.0, 1101, survey),
        ("C1s", 296.0, 280.0, 161, c1s),
        ("O1s", 538.0, 526.0, 121, o1s),
        ("Cu LMM", 580.0, 560.0, 101, cu_lmm),
    ]:
        x = region_axis(x0, x1, n) + shift
        meta = ["1", "Binding Energy (eV)", "Intensity (counts)", str(n)]
        lines += multipak_block(label, x, np.round(fn(x, rng), 1), meta=meta)
    lines.append("EOF")
    (HERE / "20260101_Synth.2.sampleB.txt").write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))

    # メタ情報が1行だけの書き出し（ラベル行の2行下からデータ。offset=2 で読む）
    rng = np.random.default_rng(13)
    lines = list(head)
    for label, x0, x1, n, fn in [
        ("C1s", 296.0, 280.0, 161, c1s),
        ("O1s", 538.0, 526.0, 121, o1s),
    ]:
        x = region_axis(x0, x1, n)
        lines += multipak_block(label, x, np.round(fn(x, rng), 1), meta=[str(n)])
    lines.append("EOF")
    (HERE / "20260101_Synth.3.sampleC.txt").write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))


# ============================================================ 抽出済み x,y CSV
def minmax(y):
    return (y - y.min()) / (y.max() - y.min())


def write_xy(path: Path, x, y, header=("x", "y")) -> None:
    rows = [",".join(header)] + [f"{a!r},{b!r}" for a, b in zip(x.tolist(), y.tolist())]
    path.write_bytes(("\r\n".join(rows) + "\r\n").encode("utf-8"))


def make_extracted() -> None:
    out = HERE / "extracted"
    out.mkdir(exist_ok=True)
    rng = np.random.default_rng(14)
    xs = region_axis(1100.0, 0.0, 1101)
    for sample, scale in (("sampleA", 1.0), ("sampleB", 0.8)):
        write_xy(out / f"{sample}_Survey.csv", xs, minmax(np.round(survey(xs, rng) * scale, 1)))
    xc = region_axis(296.0, 280.0, 161)
    for sample in ("sampleA", "sampleB"):
        write_xy(out / f"{sample}_C1s.csv", xc, minmax(np.round(c1s(xc, rng), 1)))
    # 列名が x,y でない CSV（先頭2列を使う）
    write_xy(out / "sampleC_C1s.csv", xc, np.round(c1s(xc, rng), 1), header=("BE", "Counts"))


# ============================================================ フィット結果 CSV
def fit_table(x, peaks, bg_lo, bg_hi, rng):
    """(spectrum, composite, background, [peak(背景込み)...]) を返す。"""
    background = shirley_like(x, bg_lo, bg_hi, 531.0, 0.8)
    comps = [gauss(x, mu, h, w) for mu, h, w in peaks]
    composite = background + sum(comps)
    spectrum = composite + rng.normal(0, 60, x.size)
    return spectrum, composite, background, [background + c for c in comps]


def fmt(v) -> str:
    return "" if v is None or not np.isfinite(v) else f"{v:.2f}"


def make_fit() -> None:
    out = HERE / "fit"
    out.mkdir(exist_ok=True)
    x = region_axis(538.0, 526.0, 121)

    # 1) 素直な CSV（UTF-8、LF）
    rng = np.random.default_rng(21)
    sp, comp, bg, pk = fit_table(x, [(529.8, 9000, 0.55), (531.3, 4000, 0.7), (532.8, 1500, 0.8)],
                                 1500, 2600, rng)
    rows = ["Energy,Spectrum,Composite spectrum,Background,Residual,[1/1],[2/1],[3/1]"]
    for i in range(x.size):
        vals = [x[i], sp[i], comp[i], bg[i], sp[i] - comp[i], *(p[i] for p in pk)]
        rows.append(f"{x[i]:.1f}," + ",".join(fmt(v) for v in vals[1:]))
    (out / "fit_O1s_pH7.csv").write_bytes(("\n".join(rows) + "\n").encode("utf-8"))

    # 2) Excel 経由（UTF-8 BOM、CRLF）。フィット範囲（527〜535 eV）の外はピーク列が空欄
    rng = np.random.default_rng(22)
    sp, comp, bg, pk = fit_table(x, [(529.9, 7000, 0.6), (531.4, 5500, 0.7)], 1400, 2900, rng)
    rows = ["Energy,Spectrum,Composite spectrum,Background,Residual,[1/1],[2/1]"]
    for i in range(x.size):
        inside = 527.0 <= x[i] <= 535.0
        peaks = [p[i] if inside else None for p in pk]
        rows.append(f"{x[i]:.1f}," + ",".join(
            fmt(v) for v in [sp[i], comp[i], bg[i], sp[i] - comp[i], *peaks]))
    (out / "fit_O1s_pH9_bom.csv").write_bytes(
        b"\xef\xbb\xbf" + ("\r\n".join(rows) + "\r\n").encode("utf-8"))

    # 3) 前置きの測定条件ヘッダ付き（CP932）。列名は別名、Residual 列なし（spectrum − composite で補う）
    rng = np.random.default_rng(23)
    sp, comp, bg, pk = fit_table(x, [(530.0, 5000, 0.6), (531.5, 6500, 0.75)], 1600, 3100, rng)
    rows = ["試料名,合成試料C", "測定日,2026-01-01", "", "B.E.,Raw data,Envelope,BG,Comp A,Comp B"]
    for i in range(x.size):
        rows.append(f"{x[i]:.1f}," + ",".join(fmt(v) for v in [sp[i], comp[i], bg[i], pk[0][i], pk[1][i]]))
    (out / "fit_O1s_pH11_preamble.csv").write_bytes(("\r\n".join(rows) + "\r\n").encode("cp932"))


def main() -> None:
    make_spe()
    make_multipak()
    make_extracted()
    make_fit()


if __name__ == "__main__":
    main()
