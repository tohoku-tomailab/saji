"""EC-Lab ASCII .mpt の合成データ（fixtures）を作るスクリプト。実データは使わない。

    uv run python tests/fixtures/eclab/make.py

EC-Lab の出力をまねて、1行目 EC-Lab ASCII FILE・Nb header lines・タブ区切り・列名とデータの行末の
余分なタブ・3桁指数（1.000000000000000E+000）で書く。決定的（乱数は seed 固定）。

  - cv_utf8.mpt   … ASCII（UTF-8 として読める）・CRLF。列 Ewe/V と <I>/mA。3 サイクル
  - cv_utf8_b.mpt … cv_utf8.mpt と同じ形で、電流の立ち上がりが違うもの（重ね描き用）
  - cv_comma.mpt  … CP1252（測定条件の行に ° と ²）・CRLF・カンマ小数。列 <Ewe>/V と I/mA、
                    サイクル列名は「cycle number」の空白が2つ。2 サイクル
  - not_eclab.mpt … 1行目が EC-Lab ASCII FILE ではない（読み飛ばされる）
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

HERE = Path(__file__).parent


def sci(v: float, comma: bool = False) -> str:
    """EC-Lab と同じ 3桁指数の書式（-7.658742000000000E-003）。"""
    mant, exp = f"{v:.15E}".split("E")
    s = f"{mant}E{int(exp):+04d}"
    return s.replace(".", ",") if comma else s


def cv_rows(n_cycles: int, *, e_lo: float, e_hi: float, rate: float, dt: float,
            onset: float, seed: int) -> list[tuple[float, float, float, float]]:
    """(time/s, Ewe/V, I/mA, cycle) の三角波 CV。電流 = 二重層（±）+ 指数的に立ち上がる酸化電流 + ノイズ。"""
    rng = np.random.default_rng(seed)
    half = (e_hi - e_lo) / rate
    n_half = int(round(half / dt))
    rows = []
    t = 0.0
    for cyc in range(1, n_cycles + 1):
        for k in range(2 * n_half):
            if k < n_half:
                e, sign = e_lo + rate * dt * k, 1.0
            else:
                e, sign = e_hi - rate * dt * (k - n_half), -1.0
            i_ma = 0.05 * sign + 0.02 * np.exp((e - onset) / 0.04) * (1 - 0.03 * (cyc - 1))
            i_ma += rng.normal(0, 0.002)
            rows.append((t, e, float(i_ma), float(cyc)))
            t += dt
    return rows


def write_mpt(path: Path, rows, *, columns: list[str], values, conditions: list[str],
              encoding: str, comma: bool) -> None:
    head_fixed = ["EC-Lab ASCII FILE", None, "", "Cyclic Voltammetry", ""]
    body_head = conditions + [""]
    n_header = len(head_fixed) + len(body_head) + 1   # +1 は列名の行
    head_fixed[1] = f"Nb header lines : {n_header}"
    lines = head_fixed + body_head + ["\t".join(columns) + "\t"]
    for r in rows:
        lines.append("\t".join(values(r, comma)) + "\t")
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode(encoding))


def main() -> None:
    cond = ["Run on channel : 1 (SN 0000)", "Electrode material : synthetic",
            "Reference electrode : Hg/HgO", "Comments : synthetic data for tests"]

    rows = cv_rows(3, e_lo=0.0, e_hi=0.8, rate=0.05, dt=0.4, onset=0.65, seed=1)
    write_mpt(
        HERE / "cv_utf8.mpt", rows,
        columns=["mode", "ox/red", "error", "control changes", "counter inc.", "time/s",
                 "control/V", "Ewe/V", "<I>/mA", "cycle number", "(Q-Qo)/C"],
        values=lambda r, c: ["2", "1" if r[2] > 0 else "0", "0", "0", "0", sci(r[0]), sci(r[1]),
                             sci(r[1] + 1e-4), sci(r[2]), sci(r[3]), sci(r[2] * r[0] * 1e-3)],
        conditions=cond, encoding="ascii", comma=False)

    rows = cv_rows(3, e_lo=0.0, e_hi=0.8, rate=0.05, dt=0.4, onset=0.7, seed=3)
    write_mpt(
        HERE / "cv_utf8_b.mpt", rows,
        columns=["mode", "ox/red", "error", "control changes", "counter inc.", "time/s",
                 "control/V", "Ewe/V", "<I>/mA", "cycle number", "(Q-Qo)/C"],
        values=lambda r, c: ["2", "1" if r[2] > 0 else "0", "0", "0", "0", sci(r[0]), sci(r[1]),
                             sci(r[1] + 1e-4), sci(r[2]), sci(r[3]), sci(r[2] * r[0] * 1e-3)],
        conditions=cond, encoding="ascii", comma=False)

    rows = cv_rows(2, e_lo=-0.2, e_hi=0.7, rate=0.1, dt=0.3, onset=0.6, seed=2)
    write_mpt(
        HERE / "cv_comma.mpt", rows,
        columns=["mode", "ox/red", "time/s", "<Ewe>/V", "I/mA", "cycle  number"],
        values=lambda r, c: ["2", "1" if r[2] > 0 else "0", sci(r[0], c), sci(r[1], c),
                             sci(r[2], c), sci(r[3], c)],
        conditions=cond + ["Electrode surface area : 0,196 cm²", "Temperature : 25 °C"],
        encoding="cp1252", comma=True)

    (HERE / "not_eclab.mpt").write_bytes(b"time/s\tEwe/V\tI/mA\r\n0\t0.1\t0.2\r\n")


if __name__ == "__main__":
    main()
