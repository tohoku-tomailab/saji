"""TOOL 定義から生成する CLI（人間とエージェント向け）。

  saji list [--json]                 ツールの一覧
  saji <tool> --help                 使い方（パラメータの単位・既定値・説明）
  saji <tool> [入力...] [--param 値 ...] [--params run.json]
               [--output-dir DIR] [--json] [--dry-run]

完全に非対話。出力は <output-dir>/YYYYMMDD_hhmmss-<tool>/ に置く（既定 outputs/）。
人間向けのメッセージは標準エラー出力、--json の要約だけを標準出力に出す。
終了コード: 0=成功 / 1=処理中のエラー / 2=引数や入力の誤り。
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from . import registry
from .core.runner import MANIFEST_NAME, execute, resolve_params
from .core.tool import FileInput, InputError, InputFile, Param, Tool

EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2
DEFAULT_OUTPUT_DIR = "outputs"


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    tools = registry.load_all()
    parser = build_parser(tools)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_USAGE
    if args.command == "list":
        return cmd_list(tools, as_json=args.json)
    return cmd_run(tools[args.command], args)


# ============================================================ 引数の組み立て
def flag(name: str) -> str:
    return "--" + name.replace("_", "-")


def param_help(p: Param) -> str:
    bits = [p.help] if p.help else []
    extra = []
    if p.unit:
        extra.append(f"単位 {p.unit}")
    if p.type == "range":
        extra.append("'下限,上限' の形。片側は空でよい")
    if p.type == "json":
        extra.append("JSON 文字列、または @ファイル名")
    extra.append("既定 " + ("なし" if p.default is None else json.dumps(p.default, ensure_ascii=False)))
    return _esc("".join(bits) + f"（{'、'.join(extra)}）")


def add_param(group: argparse._ArgumentGroup, p: Param) -> None:
    kw: dict[str, Any] = {"dest": f"param__{p.name}", "default": None, "help": param_help(p)}
    if p.type == "bool":
        group.add_argument(flag(p.name), action=argparse.BooleanOptionalAction, **kw)
        return
    if p.type == "choice":
        kw["choices"] = list(p.choices or ())
        kw["metavar"] = "{" + ",".join(p.choices or ()) + "}"
    else:
        kw["metavar"] = {"int": "INT", "float": "NUM", "str": "TEXT", "range": "LO,HI",
                         "json": "JSON"}[p.type]
    group.add_argument(flag(p.name), **kw)


def input_help(i: FileInput) -> str:
    acc = "、".join(i.accept) if i.accept else "任意"
    many = "複数・フォルダ可" if i.multiple else "1つ"
    need = "必須" if i.required else "任意"
    return _esc(f"{i.help}（{acc}、{many}、{need}）")


def _esc(text: str) -> str:
    """argparse は help を % 書式で展開するので、% を逃がす。"""
    return text.replace("%", "%%")


def build_tool_parser(sub, tool: Tool) -> argparse.ArgumentParser:
    epilog = []
    if tool.description:
        epilog.append(tool.description)
    if not tool.web:
        epilog.append(f"※ CLI 専用のツールです。{tool.cli_only_reason}")
    if tool.examples:
        epilog.append("例:\n" + "\n".join(f"  {e}" for e in tool.examples))
    epilog.append("出力は <output-dir>/YYYYMMDD_hhmmss-" + tool.name
                  + "/ に置き、manifest.json に条件を記録する。")
    p = sub.add_parser(tool.name, help=_esc(tool.summary), description=_esc(tool.summary),
                       epilog="\n\n".join(epilog),
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    gi = p.add_argument_group("入力")
    for k, i in enumerate(tool.inputs):
        if k == 0:
            gi.add_argument(f"input__{i.name}", nargs="*", metavar=i.name.upper(), help=input_help(i))
        else:
            gi.add_argument(flag(i.name), dest=f"input__{i.name}", nargs="+" if i.multiple else 1,
                            metavar="PATH", default=None, help=input_help(i))
    groups: dict[str, argparse._ArgumentGroup] = {}
    for prm in tool.params:
        title = f"パラメータ: {prm.group}" if prm.group else "パラメータ"
        if title not in groups:
            groups[title] = p.add_argument_group(title)
        add_param(groups[title], prm)
    g = p.add_argument_group("実行の制御")
    g.add_argument("--params", metavar="JSON", help="パラメータを JSON ファイルで一括指定する"
                   "（manifest.json もそのまま渡せる。個別の引数が優先）")
    g.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, metavar="DIR",
                   help=f"出力先の親フォルダ（既定 {DEFAULT_OUTPUT_DIR}/）")
    g.add_argument("--json", action="store_true", help="結果の要約を JSON で標準出力に出す")
    g.add_argument("--dry-run", action="store_true", help="書き込まず、何をするかだけを表示する")
    return p


def build_parser(tools: dict) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="saji", description="研究室の実験データ処理ツール群。`saji list` で一覧、"
        "`saji <tool> --help` で各ツールの使い方。",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", metavar="<tool>")
    pl = sub.add_parser("list", help="ツールの一覧")
    pl.add_argument("--json", action="store_true", help="JSON で出す")
    for mod in tools.values():
        build_tool_parser(sub, mod.TOOL)
    return parser


# ============================================================ list
def cmd_list(tools: dict, *, as_json: bool) -> int:
    if as_json:
        print(json.dumps([{"name": m.TOOL.name, "summary": m.TOOL.summary, "web": m.TOOL.web}
                          for m in tools.values()], ensure_ascii=False, indent=2))
        return EXIT_OK
    width = max(len(n) for n in tools)
    for name, mod in tools.items():
        mark = "" if mod.TOOL.web else "  [CLI専用]"
        print(f"{name.ljust(width)}  {mod.TOOL.summary}{mark}")
    return EXIT_OK


# ============================================================ 実行
def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)


def expand_paths(items: Sequence[str], spec: FileInput) -> list[Path]:
    """ファイル・フォルダ・ワイルドカードを、ファイルの一覧に展開する。

    フォルダはその下を再帰的に探し、accept に合う拡張子だけを拾う（名前順）。
    Windows の PowerShell はワイルドカードを展開しないので、ここで展開する。
    """
    out: list[Path] = []
    for item in items:
        p = Path(item)
        if p.is_dir():
            out.extend(sorted((f for f in p.rglob("*") if f.is_file() and spec.accepts(f.name)),
                              key=lambda f: str(f).lower()))
        elif p.is_file():
            out.append(p)
        elif any(ch in item for ch in "*?["):
            matched = sorted(Path(m) for m in glob.glob(item, recursive=True) if Path(m).is_file())
            if not matched:
                raise InputError(f"一致するファイルがありません: {item}")
            out.extend(matched)
        else:
            raise InputError(f"見つかりません: {item}")
    return out


def load_params_file(path: str) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputError(f"--params のファイルを読めません: {path}（{exc}）") from exc
    if isinstance(data, dict) and isinstance(data.get("params"), dict) and "tool" in data:
        data = data["params"]      # manifest.json をそのまま渡した場合
    if not isinstance(data, dict):
        raise InputError("--params の JSON はオブジェクト（{名前: 値}）にしてください")
    return data


def collect_params(tool: Tool, args: argparse.Namespace) -> dict[str, Any]:
    raw: dict[str, Any] = load_params_file(args.params) if args.params else {}
    for p in tool.params:
        v = getattr(args, f"param__{p.name}")
        if v is None:
            continue
        if p.type == "json" and isinstance(v, str) and v.startswith("@"):
            try:
                v = Path(v[1:]).read_text(encoding="utf-8-sig")
            except OSError as exc:
                raise InputError(f"{flag(p.name)} のファイルを読めません: {v[1:]}") from exc
        raw[p.name] = v
    return raw


def collect_inputs(tool: Tool, args: argparse.Namespace) -> dict[str, list[InputFile]]:
    out: dict[str, list[InputFile]] = {}
    for spec in tool.inputs:
        items = getattr(args, f"input__{spec.name}") or []
        paths = expand_paths(items, spec)
        out[spec.name] = [InputFile(name=p.name, data=p.read_bytes()) for p in paths]
    return out


def unique_dir(parent: Path, name: str) -> Path:
    """同じ秒に衝突したら -2, -3 … を付ける。"""
    d = parent / name
    n = 2
    while d.exists():
        d = parent / f"{name}-{n}"
        n += 1
    return d


def cmd_run(mod, args: argparse.Namespace) -> int:
    tool: Tool = mod.TOOL
    try:
        raw_params = collect_params(tool, args)
        inputs = collect_inputs(tool, args)
        if args.dry_run:
            return dry_run(tool, inputs, raw_params, args)
        execution = execute(mod, inputs, raw_params, runtime="cli")
    except InputError as exc:
        return fail(args, str(exc), EXIT_USAGE)
    except Exception as exc:  # noqa: BLE001 - 処理中のエラーは終了コード 1 で返す
        return fail(args, f"{type(exc).__name__}: {exc}", EXIT_ERROR)

    out_dir = unique_dir(Path(args.output_dir), execution.folder_name)
    out_dir.mkdir(parents=True)
    for f in execution.files:
        dest = out_dir / f.path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f.data)

    for line in execution.result.logs:
        eprint(line)
    for w in execution.result.warnings:
        eprint(f"[警告] {w}")
    eprint(f"-> {out_dir}（{len(execution.files)} ファイル）")
    if args.json:
        summary = execution.summary()
        summary["output_dir"] = str(out_dir.resolve())
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return EXIT_OK


def dry_run(tool: Tool, inputs: dict[str, list[InputFile]], raw_params: dict,
            args: argparse.Namespace) -> int:
    params = resolve_params(tool, raw_params)
    plan = {
        "ok": True, "dry_run": True, "tool": tool.name,
        "inputs": {k: [f.name for f in v] for k, v in inputs.items()},
        "params": params,
        "output_dir": str(Path(args.output_dir).resolve() / f"YYYYMMDD_hhmmss-{tool.name}"),
        "writes": f"処理結果のファイルと {MANIFEST_NAME}",
    }
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        eprint(f"[dry-run] {tool.name}")
        for k, v in plan["inputs"].items():
            eprint(f"  入力 {k}: {len(v)} 個 {v[:5]}{' …' if len(v) > 5 else ''}")
        for k, v in params.items():
            eprint(f"  {k} = {json.dumps(v, ensure_ascii=False)}")
        eprint(f"  出力先: {plan['output_dir']}")
    return EXIT_OK


def fail(args: argparse.Namespace, message: str, code: int) -> int:
    eprint(f"エラー: {message}")
    if getattr(args, "json", False):
        print(json.dumps({"ok": False, "error": message, "exit_code": code}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
