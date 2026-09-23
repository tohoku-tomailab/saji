"""ツールの実行（CLI と Web の共通部分）。

  1. パラメータを定義に沿って検証・変換し、既定値で埋める
  2. 入力ファイルを検証する
  3. run() を呼ぶ
  4. 成果物の図（export=True）を SVG / PNG / 図のJSON / 図のデータCSV にする
  5. manifest.json を作る

ファイルへの書き込み（CLI）と zip の保存（Web）だけが、それぞれの層の仕事になる。
"""

from __future__ import annotations

import hashlib
import io
import json
import platform
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import ModuleType
from typing import Any, Callable, Mapping

from .plot.checks import non_arial_texts
from .plot.export import figure_to_csv
from .tool import InputError, InputFile, OutputFile, Result, Tool
from .version import git_commit, is_pyodide, package_version, pyodide_version

MANIFEST_NAME = "manifest.json"


@dataclass
class Execution:
    """1回の実行の結果。files は出力フォルダに置く全ファイル（manifest を含む）。"""

    tool: Tool
    params: dict[str, Any]
    result: Result
    files: list[OutputFile]
    manifest: dict[str, Any]
    folder_name: str
    previews: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """CLI の --json や Web の画面に出す要約（出力フォルダの場所は各層が足す）。"""
        return {
            "ok": True,
            "tool": self.tool.name,
            "folder": self.folder_name,
            "files": [f.path for f in self.files],
            "n_inputs": len(self.manifest["inputs"]),
            "warnings": list(self.result.warnings),
            "logs": list(self.result.logs),
            "data": self.result.data,
        }


# ============================================================ 検証
def resolve_params(tool: Tool, raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """生のパラメータ（文字列や JSON 値）を型変換し、未指定は既定値で埋める。"""
    raw = dict(raw or {})
    known = {p.name for p in tool.params}
    unknown = sorted(k for k in raw if k not in known)
    if unknown:
        raise InputError(f"{tool.name} に無いパラメータです: {', '.join(unknown)}"
                         f"（使えるもの: {', '.join(sorted(known)) or 'なし'}）")
    out: dict[str, Any] = {}
    for p in tool.params:
        v = p.coerce(raw[p.name]) if p.name in raw else None
        out[p.name] = p.default if v is None else v
    return out


def check_inputs(tool: Tool, inputs: Mapping[str, list[InputFile]]) -> list[str]:
    """入力を検証する。直せない誤りは InputError、気になる点は警告として返す。"""
    warnings: list[str] = []
    known = {i.name for i in tool.inputs}
    extra = [k for k, v in inputs.items() if k not in known and v]
    if extra:
        raise InputError(f"{tool.name} に無い入力です: {', '.join(extra)}")
    for spec in tool.inputs:
        files = inputs.get(spec.name) or []
        if spec.required and not files:
            raise InputError(f"入力 {spec.name} が必要です（{spec.help or '、'.join(spec.accept)}）")
        if not spec.multiple and len(files) > 1:
            raise InputError(f"入力 {spec.name} は1つだけです（{len(files)} 個指定されました）")
        for f in files:
            if not spec.accepts(f.name):
                warnings.append(f"{f.name} は想定外の拡張子です（{spec.name} は {', '.join(spec.accept)}）")
    return warnings


# ============================================================ 実行
def execute(
    module: ModuleType,
    inputs: Mapping[str, list[InputFile]],
    raw_params: Mapping[str, Any] | None = None,
    *,
    runtime: str = "cli",
    now: Callable[[], datetime] | None = None,
    export_figures: bool = True,
) -> Execution:
    """ツールを実行して、出力フォルダに置く全ファイルを bytes で返す。"""
    tool: Tool = module.TOOL
    clock = now or (lambda: datetime.now().astimezone())
    params = resolve_params(tool, raw_params)
    input_warnings = check_inputs(tool, inputs)

    started = clock()
    result: Result = module.run({k: list(v) for k, v in inputs.items()}, params)
    if not isinstance(result, Result):
        raise TypeError(f"{tool.name}.run() は Result を返してください")
    result.warnings[:0] = input_warnings

    files = list(result.files)
    previews: list[dict[str, Any]] = []
    for figure in result.figures:
        bad = non_arial_texts(figure.spec)
        if bad:
            result.warn(f"図 {figure.name} に Arial で表示できない文字（日本語など）が含まれています:"
                        f" {', '.join(bad[:3])}{' …' if len(bad) > 3 else ''}")
        previews.append({"name": figure.name, "spec": figure.spec})
        if figure.export and export_figures:
            files.extend(_export_figure(figure.name, figure.spec, result))
    _check_unique_paths(files)

    finished = clock()
    manifest = build_manifest(tool, params, inputs, files, result, started, finished, runtime)
    files.append(OutputFile(MANIFEST_NAME, (json.dumps(manifest, ensure_ascii=False, indent=2)
                                            + "\n").encode("utf-8")))
    return Execution(tool=tool, params=params, result=result, files=files, manifest=manifest,
                     folder_name=folder_name(tool.name, started), previews=previews)


def _export_figure(name: str, spec: dict[str, Any], result: Result) -> list[OutputFile]:
    out = [
        OutputFile(f"{name}.plotly.json", json.dumps(spec, ensure_ascii=False).encode("utf-8")),
        OutputFile(f"{name}_data.csv", figure_to_csv(spec).encode("utf-8-sig")),
    ]
    try:
        from .plot.mpl import render
        out.append(OutputFile(f"{name}.svg", render(spec, "svg")))
        out.append(OutputFile(f"{name}.png", render(spec, "png")))
    except ImportError as exc:
        result.warn(f"図 {name} の画像を作れませんでした（matplotlib がありません: {exc}）")
    return out


def _check_unique_paths(files: list[OutputFile]) -> None:
    seen: set[str] = set()
    for f in files:
        key = f.path.lower()
        if key in seen or f.path == MANIFEST_NAME:
            raise RuntimeError(f"出力ファイル名が重複しています: {f.path}")
        seen.add(key)


def folder_name(tool_name: str, started: datetime) -> str:
    """出力フォルダ名 ``YYYYMMDD_hhmmss-{tool}``。"""
    return f"{started:%Y%m%d_%H%M%S}-{tool_name}"


def clock_with_offset(offset_minutes: int) -> Callable[[], datetime]:
    """ブラウザの時差（JS の -getTimezoneOffset() 分）で現在時刻を返す時計。"""
    tz = timezone(timedelta(minutes=offset_minutes))
    return lambda: datetime.now(tz)


# ============================================================ manifest
def build_manifest(tool: Tool, params: dict[str, Any], inputs: Mapping[str, list[InputFile]],
                   files: list[OutputFile], result: Result, started: datetime,
                   finished: datetime, runtime: str) -> dict[str, Any]:
    """manifest.json の中身。入力はファイル名だけを記録する（フルパスは残さない）。"""
    return {
        "tool": tool.name,
        "tool_version": package_version(),
        "git_commit": git_commit(),
        "runtime": runtime,
        "python_version": platform.python_version(),
        "pyodide_version": pyodide_version() if is_pyodide() else None,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "params": params,
        "inputs": [
            {"input": role, "name": f.name, "size": len(f.data),
             "sha256": hashlib.sha256(f.data).hexdigest()}
            for role, fs in inputs.items() for f in fs
        ],
        "outputs": [f.path for f in files],
        "warnings": list(result.warnings),
    }


# ============================================================ zip（Web 用）
def to_zip(execution: Execution) -> bytes:
    """出力フォルダと同じ構成の zip（フォルダ名の下に全ファイル）を作る。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in execution.files:
            zf.writestr(f"{execution.folder_name}/{f.path}", f.data)
    return buf.getvalue()
