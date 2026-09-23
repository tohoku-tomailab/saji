"""echem-extract: ポテンショスタットCSVから本測定を抜き出し、平均電位・溶液抵抗を算出する。"""

from __future__ import annotations

import codecs
from typing import Any

from ..core.plot import get_style
from ..core.tool import FileInput, InputError, InputFile, Param, Result, Tool
from ..techniques import echem

METRICS_CSV = "echem_metrics.csv"
METRICS_JSON = "echem_metrics.json"

TOOL = Tool(
    name="echem-extract",
    summary="ポテンショスタット（《...》区切りCSV）から本測定データを抜き出し、平均電位・溶液抵抗を算出する",
    description=(
        "ファイルごと・フェイズごとに測定データを <名前>_main.csv（本測定が複数サイクルなら "
        "<名前>_main_cycle1.csv, _main_cycle2.csv …）として出す。列名は装置のまま、文字コードは "
        "既定 utf-8-sig。数値指標（平均電位・溶液抵抗など）は全ファイル分を echem_metrics.csv / "
        "echem_metrics.json にまとめ、--json の data.metrics にも入れる。"
        "平均電位は本測定の 電位E の平均（種別 列があれば種別ごとの平均も）。"
        "溶液抵抗は Im Z の符号が変わる隣接2点の Re Z から求める（既定は高周波側の最初の交差）。"
        "入力形式は docs/data-formats.md の『ポテンショスタット CSV』を参照。"
    ),
    inputs=[
        FileInput("raw", accept=[".csv"], multiple=True,
                  help="ポテンショスタットの出力CSV（CP932 など。文字コードは自動判定）"),
    ],
    params=[
        Param("phase", str, "main", group="抽出", label="フェイズ",
              help="抽出するフェイズ: main（本測定）/ all（全部）/ コード（例 0x0601）/ 名前の一部（例 自然電位）"),
        Param("cycle", int, None, group="抽出", label="サイクル番号",
              help="このサイクル番号のフェイズだけにする（未指定なら全サイクル）"),
        Param("data", bool, True, group="抽出", label="測定データCSVを出す",
              help="フェイズごとの測定データCSVを出す（オフにすると指標だけ）"),
        Param("rename", bool, False, group="抽出", advanced=True, label="列名をASCIIにする",
              help="列名を ASCII の論理名（time_s, E_V, I_A, WE_CE_V, freq_Hz, ReZ_ohm, ImZ_ohm, kind など）に付け替える"),
        Param("encoding", str, "utf-8-sig", group="抽出", advanced=True, label="出力CSVの文字コード",
              help="測定データCSVの文字コード（utf-8-sig は Excel でそのまま開ける。cp932 なども可）"),
        Param("metrics", choices=echem.METRIC_MODES, default="auto", group="指標", label="算出する指標",
              help="auto=測定種と列から判断 / potential=平均電位 / resistance=溶液抵抗 / all=両方 / none=算出しない"),
        Param("avg_range", "range", None, unit="s", group="指標", label="平均する時間範囲",
              help="平均電位を求める 時間t の範囲（例 1500, で 1500 s 以降。CP で定常部だけを平均したいとき）。未指定なら本測定の全体"),
        Param("rs_method", choices=echem.RS_METHODS, default="mean", group="指標", advanced=True,
              label="溶液抵抗の求め方", help="mean=交差の前後2点の Re Z の平均 / interp=Im Z=0 への線形内挿"),
        Param("rs_crossing", str, "first", group="指標", advanced=True, label="使う交差",
              help="使う Im Z の符号反転点: first=高周波側の最初 / last=最後 / 0 始まりの番号（負なら後ろから）"),
    ],
    packages=["numpy", "pandas"],
    plots=False,
    examples=[
        "saji echem-extract CP-sample.CSV --avg-range 1500,",
        "saji echem-extract IMP-sample.CSV --no-data --json",
        "saji echem-extract ./raw --phase all",
    ],
)


def _check_params(params: dict) -> None:
    """kaiseki-tool では処理の途中で落ちていた指定の誤りを、先に InputError にする。"""
    try:
        codecs.lookup(params["encoding"])
    except LookupError as exc:
        raise InputError(f"encoding に未知の文字コードが指定されました: {params['encoding']}") from exc
    try:
        echem.check_crossing(params["rs_crossing"])
    except ValueError as exc:
        raise InputError(f"rs_crossing: {exc}") from exc


def run(inputs: dict[str, list[InputFile]], params: dict) -> Result:
    result = Result()
    _check_params(params)
    st = get_style(None)
    mode = params["metrics"]

    records: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen_stems: set[str] = set()
    n_ok = 0

    for f in inputs["raw"]:
        if f.stem.lower() in seen_stems:
            msg = "同じ名前のファイルが既にあるので飛ばしました（出力ファイル名が重なるため）"
            result.warn(f"{f.name}: {msg}")
            skipped.append({"file": f.name, "reason": msg})
            continue
        seen_stems.add(f.stem.lower())

        try:
            ef = echem.parse_bytes(f.data, f.name)
        except Exception as exc:                      # noqa: BLE001 - 一括処理を止めない
            msg = f"読み込みに失敗しました（{type(exc).__name__}: {exc}）"
            result.warn(f"{f.name}: {msg}")
            skipped.append({"file": f.name, "reason": msg})
            continue
        picked = ef.select_phases(params["phase"], params["cycle"])
        if not picked:
            cyc = f", cycle={params['cycle']}" if params["cycle"] is not None else ""
            msg = (f"該当フェイズがありません（phase={params['phase']}{cyc}）。"
                   f"含まれるフェイズ: {ef.describe_phases()}")
            result.warn(f"{f.name}: {msg}")
            skipped.append({"file": f.name, "reason": msg})
            continue

        n_ok += 1
        file_records = _process_phases(result, f, ef, picked, params)
        records.extend(file_records)

        fig = echem.preview_figure(
            [(echem.phase_tag(ph, i, len(picked) > 1), ph) for i, ph in enumerate(picked)],
            echem.detect_kind(ef, picked[0].df), st,
            title=f.name if f.name.isascii() else None, records=file_records)
        if fig is not None:
            result.add_figure(f"{f.stem}_preview", fig, export=False)

    if n_ok == 0:
        details = " / ".join(f"{s['file']}: {s['reason']}" for s in skipped)
        raise InputError(f"処理できたファイルがありません。{details}")

    if mode != "none" and records:
        result.add_file(METRICS_CSV, echem.metrics_csv(records))
        result.add_file(METRICS_JSON, echem.metrics_json(records))
    if not params["data"] and mode == "none":
        result.warn("data=false かつ metrics=none なので、出力するものがありません")

    result.data["metrics"] = records
    result.data["skipped"] = skipped
    return result


def _process_phases(result: Result, f: InputFile, ef: echem.EchemFile,
                    phases: list[echem.Phase], params: dict) -> list[dict[str, Any]]:
    """1ファイル分のフェイズを CSV にし、指標を集計する。"""
    records: list[dict[str, Any]] = []
    multiple = len(phases) > 1
    used: set[str] = set()
    for i, ph in enumerate(phases):
        result.log(f"[OK] {f.name}: {ph.label}（{len(ph.df)}点）")
        if params["data"]:
            tag = echem.phase_tag(ph, i, multiple)
            if tag.lower() in used:
                # 同じコード・同じサイクルのフェイズが2つある（kaiseki-tool では上書きしていた）
                new = f"{tag}_{i}"
                result.warn(f"{f.name}: 出力名 {tag} が重なるので {new} にしました")
                tag = new
            used.add(tag.lower())
            path = f"{f.stem}_{tag}.csv"
            try:
                result.add_file(path, echem.phase_csv(ph, rename=params["rename"],
                                                      encoding=params["encoding"]))
            except UnicodeEncodeError as exc:
                raise InputError(f"文字コード {params['encoding']} では書けない文字があります"
                                 f"（{f.name}: {exc.object[exc.start:exc.end]!r}）。"
                                 "utf-8-sig を使うか rename を指定してください") from exc
            result.log(f"  -> {path}")
        if params["metrics"] != "none":
            rec = echem.summarize_phase(ef, ph, metrics=params["metrics"],
                                        time_range=params["avg_range"],
                                        rs_method=params["rs_method"],
                                        rs_crossing=params["rs_crossing"])
            records.append(rec)
            for line in echem.format_metrics(rec):
                result.log(f"  {line}")
            for w in echem.metric_warnings(rec):
                result.warn(f"{f.name}（{ph.label}）: {w}")
    return records
