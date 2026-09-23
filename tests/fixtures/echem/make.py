"""電気化学（ポテンショスタット出力）の合成データ（fixtures）を作るスクリプト。実データは使わない。

    uv run python tests/fixtures/echem/make.py

装置の出力をまねて CP932・CRLF・《...》区切り・B列始まりの表・3桁指数（1.000000e+000）で書く。
決定的（乱数は seed 固定）なので、何度実行しても同じファイルになる。

  - cp_synth.CSV    … CP（0x0506）。自然電位測定 → 本測定サイクル1（種別 第1/第2電流）→
                      本測定サイクル2（《サイクル情報》なし）
  - imp_synth.CSV   … IMP（0x051C）。自然電位測定 → 本測定（高周波→低周波。Im Z の符号反転が
                      高周波側に1つ + 低周波側のノイズで複数）
  - unknown_synth.CSV … 未知の測定項目コード（0x0999）。本測定1つ（列から CP と推定される）
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent


def sci(v: float) -> str:
    """装置と同じ 3桁指数の書式（-7.658742e-003）。"""
    mant, exp = f"{v:.6e}".split("e")
    return f"{mant}e{int(exp):+04d}"


def table(header: list[str], rows: list[list[str]]) -> list[str]:
    """B列始まりの表。ヘッダ行だけ末尾にカンマが付く（装置の癖）。"""
    return ["," + ",".join(header) + ","] + ["," + ",".join(r) for r in rows]


def phase(code: str, name: str, cycle: int, header: list[str], rows: list[list[str]], *,
          start: str | None, end: str | None) -> list[str]:
    lines = ["《測定フェイズヘッダ》", f",フェイズ情報,{code},{name}", f",サイクル番号,{cycle}",
             f",測定点数,{len(rows)}", ""]
    if start is not None:
        lines += ["《サイクル情報》", f",開始時間,{start}", f",終了時間,{end}", ""]
    lines += ["《測定サンプリングヘッダ》", f",データ数,{len(rows)}", f",データ項目数,{len(header)}", ""]
    lines += ["《測定データ》", *table(header, rows), ""]
    return lines


def write(name: str, lines: list[str]) -> None:
    (HERE / name).write_bytes(("\r\n".join(lines) + "\r\n").encode("cp932"))


def file_head(code: str, item: str, title: str, info: list[str], cond: list[str]) -> list[str]:
    return ["《ファイル情報》", f",測定項目情報,{code},{item}", f",測定タイトル,{title}",
            ",解析バージョン,2", "", "《測定情報》", *info, "", "《測定条件》", *cond, "",
            "《PGS設定》", ",電流レンジ,100mA", ",フィルタ,OFF", ""]


def tail() -> list[str]:
    return ["", "《解析データヘッダ》", ",解析データ数,0"]


# ============================================================ CP
def make_cp() -> None:
    rng = np.random.default_rng(11)
    lines = file_head("0x0506", "CP ｸﾛﾉﾎﾟﾃﾝｼｮﾒﾄﾘ", "合成CP",
                      [",試料,合成試料A", ",面積,1.000000,cm2", ",参照電極,Ag/AgCl",
                       ",電解液,0.1M KHCO3"],
                      [",[本測定]", ",,第1設定電流,-10,mA", ",,第1時間,60,s",
                       ",,第2設定電流,-20,mA", ",,第2時間,60,s"])

    # 自然電位測定（10点）
    rows = []
    for k in range(1, 11):
        e = -0.012 + 0.0004 * k + rng.normal(0, 2e-4)
        rows.append([sci(k), sci(e), sci(0.0), sci(e)])
    lines += phase("0x0601", "自然電位測定", 1, ["1 時間t", "2 電位E", "3 電流I", "22 自然電位"],
                   rows, start="2026-01-01 10:00:00", end="2026-01-01 10:00:10")

    # 本測定（2サイクル。第1電流 60 s → 第2電流 60 s。電位は緩やかにドリフト）
    for cycle, start in ((1, "2026-01-01 10:00:10"), (2, None)):
        rows = []
        for k in range(1, 121):
            first = k <= 60
            i = -0.010 if first else -0.020
            e = (-1.05 if first else -1.18) - 0.04 * (1 - math.exp(-k / 25)) \
                - 0.01 * (cycle - 1) + rng.normal(0, 1.5e-3)
            rows.append([sci(k), sci(e), sci(i), sci(e - 0.9 + rng.normal(0, 2e-3)),
                         "第1電流" if first else "第2電流"])
        lines += phase("0x0600", "本測定", cycle,
                       ["1 時間t", "2 電位E", "3 電流I", "4 WE/CE", "種別"], rows,
                       start=start, end="2026-01-01 10:02:10" if start else None)
    write("cp_synth.CSV", lines + tail())


# ============================================================ IMP
def impedance(f: np.ndarray) -> np.ndarray:
    """L + Rs + (Rct || C) の等価回路（高周波側に誘導成分があり Im Z の符号が変わる）。"""
    w = 2 * np.pi * f
    L, rs, rct, c = 1.0e-5, 12.3, 40.0, 1.0e-5
    return 1j * w * L + rs + rct / (1 + 1j * w * rct * c)


def make_imp() -> None:
    rng = np.random.default_rng(22)
    lines = file_head("0x051C", "IMP／定電位 定電位交流ｲﾝﾋﾟｰﾀﾞﾝｽ測定", "合成IMP",
                      [",試料,合成試料B", ",面積,0.500000,cm2", ",参照電極,Ag/AgCl"],
                      [",[本測定]", ",,設定電位,-0.700,V", ",,振幅,10,mV",
                       ",,開始周波数,100000,Hz", ",,終了周波数,0.1,Hz"])
    rows = [[sci(k), sci(-0.70 + 1e-4 * k), sci(-0.70 + 1e-4 * k)] for k in range(1, 4)]
    lines += phase("0x0601", "自然電位測定", 1, ["1 時間t", "2 電位E", "22 自然電位"], rows,
                   start="2026-01-01 11:00:00", end="2026-01-01 11:00:03")

    f = 10 ** np.linspace(5, -1, 61)           # 高周波 → 低周波（10点/桁）
    z = impedance(f)
    re, im = z.real.copy(), z.imag.copy()
    low = f < 1.0                               # 低周波側はノイズで Im Z の符号が揺れる
    im[low] = 0.015 * np.sign(np.sin(np.arange(low.sum()) * 2.1)) + rng.normal(0, 0.003, low.sum())
    re[low] = re[low] + rng.normal(0, 0.05, low.sum())
    absz = np.hypot(re, im)
    ph = np.degrees(np.arctan2(im, re))
    rows = []
    for k in range(f.size):
        rows.append([sci(k + 1), sci(-0.700 + rng.normal(0, 2e-4)), sci(-1.0e-4),
                     sci(-1.5), sci(f[k]), sci(re[k]), sci(im[k]), sci(absz[k]), sci(ph[k])])
    lines += phase("0x0600", "本測定", 1,
                   ["1 時間t", "2 電位E", "3 電流I", "4 WE/CE", "16 周波数　f", "17 Re Z",
                    "18 Im Z", "19 |Z|", "20 位相Φ"], rows,
                   start="2026-01-01 11:00:03", end="2026-01-01 11:10:00")
    write("imp_synth.CSV", lines + tail())


# ============================================================ 未知コード
def make_unknown() -> None:
    rng = np.random.default_rng(33)
    lines = ["《ファイル情報》", ",測定項目情報,0x0999,未知の測定", ",測定タイトル,", "",
             "《測定情報》", ",試料,", ""]
    rows = [[sci(0.5 * k), sci(-0.5 - 0.001 * k + rng.normal(0, 5e-4)), sci(-0.001)]
            for k in range(1, 41)]
    lines += phase("0x0600", "本測定", 1, ["1 時間t", "2 電位E", "3 電流I"], rows,
                   start="2026-01-02 09:00:00", end="2026-01-02 09:00:20")
    write("unknown_synth.CSV", lines + tail())


def main() -> None:
    make_cp()
    make_imp()
    make_unknown()


if __name__ == "__main__":
    main()
