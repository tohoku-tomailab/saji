"""合成データ（fixtures）を作るスクリプト。実データは使わない。

    uv run python tests/fixtures/make_fixtures.py

決定的（乱数は seed 固定）なので、何度実行しても同じファイルになる。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

HERE = Path(__file__).parent


def gauss(x, mu, h, w):
    return h * np.exp(-0.5 * ((x - mu) / w) ** 2)


def smartlab_txt(name: str, peaks: list[tuple[float, float, float]], seed: int) -> None:
    """SmartLab .TXT 風（CP932 のヘッダ + 2列）の合成パターン。"""
    rng = np.random.default_rng(seed)
    x = np.round(np.arange(20.0, 80.0 + 1e-9, 0.02), 2)
    y = 300 + 400 * np.exp(-(x - 20) / 15)            # なだらかな背景
    for mu, h, w in peaks:
        y = y + gauss(x, mu, h, w)
    y = np.round(y + rng.normal(0, 8, x.size))
    lines = [
        "Sample\t合成試料 " + name,
        "Start\t20.0000",
        "Stop\t80.0000",
        "Step\t0.0200",
        "X-Ray\t40 kV , 30 mA",
        "ScanningMode\tContinuous",
        "*RAS_INT_START",
    ]
    lines += [f"{a:.4f} {b:.0f}" for a, b in zip(x, y)]
    lines.append("*RAS_INT_END")
    (HERE / "xrd" / f"{name}.TXT").write_bytes(("\r\n".join(lines) + "\r\n").encode("cp932"))


def main() -> None:
    (HERE / "xrd").mkdir(exist_ok=True)
    smartlab_txt("synthA", [(43.30, 3000, 0.15), (50.43, 1300, 0.18), (74.13, 700, 0.2)], seed=1)
    smartlab_txt("synthB", [(38.40, 900, 0.2), (43.32, 2000, 0.15), (50.45, 800, 0.18)], seed=2)
    (HERE / "xrd" / "peaks.json").write_text(
        '[\n  [43.30, "Cu(111)", "v", "tab:red"],\n  [50.43, "Cu(200)", "v", "tab:red"],\n'
        '  [74.13, "Cu(220)", "v", "tab:red"],\n  [38.40, "TiO2(101)", "^", "tab:blue"]\n]\n',
        encoding="utf-8")


if __name__ == "__main__":
    main()
