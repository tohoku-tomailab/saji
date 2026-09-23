"""CO2RR の合成データ（fixtures）を作るスクリプト。実データは使わない。

    uv run python tests/fixtures/co2rr/make.py

値は手で決めた架空の数値（乱数なし）なので、何度実行しても同じファイルになる。
作るファイル（どれも列名で解決できることを確かめるための崩し方をしてある）:

  standard.csv      … 標準の列（sample_id, sample_name, 生成物8種, potential）
  grouped.csv       … group 列あり（group で群化される）
  label_group.csv   … sample_id / sample_name が無く、label と group だけの表
  preamble.csv      … データの前に測定条件の前置き（CP932、日本語）がある
  aliases.csv       … 生成物などの列名が別名（Hydrogen, ethylene, 電位 …）で、列順も入れ替え
  empty_cells.csv   … 液体生成物・電位・試料名の空欄、末尾の空列（,, 由来）
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent

STD_HEADER = ["sample_id", "sample_name", "H2", "CO", "CH4", "C2H4", "HCOOH", "EtOH",
              "1-PrOH", "CH3COOH", "potential"]

# 架空の試料（名前に pH が入っていて、label_pattern で pH ごとにまとめられる）
STD_ROWS = [
    ["S01_CupH7fA", "synthCupH7fA", "21.0", "36.5", "11.2", "24.8", "3.4", "8.8", "0.7", "6.1", "-1.52"],
    ["S02_CupH9fA", "synthCupH9fA", "29.5", "26.0", "21.4", "16.9", "4.4", "7.2", "0.5", "6.6", "-1.83"],
    ["S03_CupH7r", "synthCupH7r", "23.1", "39.2", "8.7", "24.1", "2.6", "8.1", "0.6", "6.4", "-1.71"],
    ["S04_CupH11fA", "synthCupH11fA", "35.0", "20.3", "15.5", "12.2", "5.1", "5.9", "1.2", "4.8", "-1.64"],
    ["S05_CupH7fA", "synthCupH7fA", "18.4", "37.7", "8.3", "30.6", "2.9", "7.5", "0.9", "5.2", "-1.66"],
    ["S06_CupH9fA", "synthCupH9fA", "38.2", "18.6", "24.7", "9.4", "3.8", "4.1", "0.3", "2.7", "-1.68"],
    ["S07_CupH11fA", "synthCupH11fA", "31.6", "22.9", "17.8", "13.5", "4.7", "6.3", "1.0", "5.5", "-1.61"],
]


def write(name: str, lines: list[str], *, encoding: str = "utf-8") -> None:
    (HERE / name).write_bytes(("\n".join(lines) + "\n").encode(encoding))


def csv_lines(header: list[str], rows: list[list[str]]) -> list[str]:
    return [",".join(header)] + [",".join(r) for r in rows]


def standard() -> None:
    write("standard.csv", csv_lines(STD_HEADER, STD_ROWS))


def grouped() -> None:
    header = STD_HEADER[:2] + ["group"] + STD_HEADER[2:]
    groups = ["Cu-A", "Cu-B", "Cu-A", "Cu-C", "Cu-A", "Cu-B", "Cu-C"]
    rows = [r[:2] + [g] + r[2:] for r, g in zip(STD_ROWS, groups)]
    write("grouped.csv", csv_lines(header, rows))


def label_group() -> None:
    lines = [
        "label,group,H2,CO,CH4,C2H4,potential",
        "s1,gA,10.0,40.0,20.0,25.0,-1.00",
        "s2,gA,20.0,30.0,22.0,24.0,-1.20",
        "s3,gB,50.0,30.0,5.0,10.0,-1.50",
        "s4,gC,15.5,44.5,12.0,20.0,-1.35",
        "s5,gC,17.5,41.0,13.0,21.5,-1.30",
    ]
    write("label_group.csv", lines)


def preamble() -> None:
    lines = [
        "測定条件,合成データ（架空）",
        "電解液,0.1 M KHCO3",
        "電流密度,-10 mA cm-2",
        "",
    ] + csv_lines(STD_HEADER, STD_ROWS[:5])
    write("preamble.csv", lines, encoding="cp932")


def aliases() -> None:
    # 列順を入れ替え、列名を別名にする（論理名 → 別名）
    rename = {"sample_id": "ID", "sample_name": "試料名", "H2": "Hydrogen", "CO": "CO",
              "CH4": "methane", "C2H4": "ethylene", "HCOOH": "Formic acid", "EtOH": "Ethanol",
              "1-PrOH": "n-PrOH", "CH3COOH": "Acetic acid", "potential": "電位"}
    order = ["potential", "C2H4", "sample_name", "CO", "H2", "CH3COOH", "EtOH", "sample_id",
             "CH4", "1-PrOH", "HCOOH"]
    idx = [STD_HEADER.index(c) for c in order]
    header = [rename[c] for c in order]
    rows = [[r[i] for i in idx] for r in STD_ROWS]
    write("aliases.csv", csv_lines(header, rows))


def empty_cells() -> None:
    lines = [
        "sample_id,sample_name,H2,CO,CH4,C2H4,HCOOH,EtOH,1-PrOH,CH3COOH,potential,,",
        "E01,catA,20.0,38.0,10.0,26.0,3.5,9.0,0.7,6.5,-1.50,,",
        "E02,catA,18.0,38.0,8.0,31.0,,,,,-1.66,,",
        "E03,catB,39.0,19.0,25.0,9.0,,,,,,,",
        "E04,catB,28.0,27.0,22.0,17.0,4.6,7.5,0.4,6.8,,,",
        "E05,catC,30.0,,20.0,15.0,,,,,-1.40,,",
        "E06,,25.0,30.0,15.0,20.0,,,,,-1.45,,",
    ]
    write("empty_cells.csv", lines)


def main() -> None:
    standard()
    grouped()
    label_group()
    preamble()
    aliases()
    empty_cells()


if __name__ == "__main__":
    main()
