"""kaiseki-tool の出力から echem-extract のゴールデンデータを作り直すスクリプト。

    uv run python tests/golden/echem-extract/from_kaiseki.py <kaiseki-tool のフォルダ>

kaiseki-tool 側で ``uv run kaiseki echem extract`` を CASES の引数で実行し、出力を
このフォルダの <ケース名>/ に置く。そのとき次の2点だけを変える（中身の数値は変えない）。

  - 改行を LF にそろえる（kaiseki-tool は Windows では CRLF で書く）。
  - 指標の ``path``（入力のフルパス）を落とす（saji は出力にフルパスを残さない）。
    echem_metrics.csv は path 列を除いて csv モジュールで書き直す（pandas と同じ
    QUOTE_MINIMAL なので、ほかの列の書式は変わらない）。

ゴールデンデータを作り直すのは、出力が変わる変更を意図して行い、人間が承認したときだけ。
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
FIXTURES = HERE.parent.parent / "fixtures" / "echem"

#: ケース名 -> (入力ファイル。None ならフォルダ一括, kaiseki の追加引数)
CASES: dict[str, tuple[str | None, list[str]]] = {
    "cp_default": ("cp_synth.CSV", []),
    "imp_default": ("imp_synth.CSV", []),
    "unknown_default": ("unknown_synth.CSV", []),
    "cp_all_rename": ("cp_synth.CSV", ["--phase", "all", "--rename", "--avg-range", "60,"]),
    "cp_cycle2_all": ("cp_synth.CSV", ["--cycle", "2", "--metrics", "all"]),
    "cp_cp932": ("cp_synth.CSV", ["--encoding", "cp932", "--avg-range", ",30"]),
    "imp_interp_last": ("imp_synth.CSV", ["--rs-method", "interp", "--rs-crossing", "last"]),
    "imp_rest": ("imp_synth.CSV", ["--phase", "0x0601"]),
    "imp_crossing2": ("imp_synth.CSV", ["--rs-crossing", "-2", "--metrics", "resistance", "--no-data"]),
    "batch": (None, []),
}


def lf(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def drop_path_json(data: bytes) -> bytes:
    records = json.loads(data.decode("utf-8"))
    for r in records:
        r.pop("path", None)
    return json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8")


def drop_path_csv(data: bytes) -> bytes:
    rows = list(csv.reader(io.StringIO(lf(data).decode("utf-8-sig"))))
    k = rows[0].index("path")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for row in rows:
        w.writerow(row[:k] + row[k + 1:])
    return buf.getvalue().encode("utf-8-sig")


def main(kaiseki: Path) -> None:
    for case, (name, extra) in CASES.items():
        dest = HERE / case
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            src = str(FIXTURES / name) if name else str(FIXTURES)
            cmd = ["uv", "run", "kaiseki", "echem", "extract", src, "--out-dir", str(out)]
            if name:
                cmd += ["--metrics-out", str(out / "echem_metrics.json")]
            subprocess.run(cmd + extra, cwd=kaiseki, check=True, capture_output=True)
            for f in sorted(out.iterdir()):
                data = f.read_bytes()
                if f.name == "echem_metrics.json":
                    data = drop_path_json(lf(data))
                elif f.name == "echem_metrics.csv":
                    data = drop_path_csv(data)
                else:
                    data = lf(data)
                (dest / f.name).write_bytes(data)
        print(case, sorted(p.name for p in dest.iterdir()))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
