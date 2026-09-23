"""ツール定義の型（唯一の情報源）。

各ツールは ``tools/<name>.py`` に、宣言的な ``TOOL = Tool(...)`` と純粋な処理関数
``run(inputs, params) -> Result`` を置く。CLI の引数・Web のフォーム・``--help``・
ドキュメントの一覧は、すべてこの定義から生成する。**同じ情報を二か所以上に書かないこと。**

``run()`` の約束（docs/design.md）:
  - ファイルシステムに触れない（入力は bytes、出力も bytes）。
  - 画面について何も知らない（print しない。伝えたいことは Result のログ・警告へ）。
  - 決定的にする。ネットワークに接続しない。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable

# パラメータの種類。JSON で表現できる単純な型だけに限る（docs/decisions/0002）。
#   int / float / str / bool / choice  … HANDOFF §3.2 の基本型
#   range  … [下限, 上限]（片側 None 可）。軸範囲など
#   json   … 見た目の細かい辞書など、フォームで表しにくい設定の逃げ道（例外扱い）
PARAM_KINDS = ("int", "float", "str", "bool", "choice", "range", "json")

_PY_TYPES = {int: "int", float: "float", str: "str", bool: "bool"}


class InputError(Exception):
    """引数や入力の誤り（CLI の終了コード 2）。利用者が直せる問題に使う。"""


@dataclass(frozen=True)
class Param:
    """処理パラメータ1つ分の定義。

    type には Python の型（int / float / str / bool）か、"choice" / "range" / "json"
    を渡す。choices を渡すと自動で "choice" になる。default が None のパラメータは
    「未指定なら使わない」任意の値として扱う。
    """

    name: str
    type: Any = str
    default: Any = None
    help: str = ""
    label: str = ""          # Web のフォームに出す表示名（空なら name）
    unit: str | None = None
    choices: tuple[str, ...] | None = None
    min: float | None = None
    max: float | None = None
    group: str = ""          # フォームの見出し（例 "背景除去"、"図"）
    advanced: bool = False   # Web では「詳細設定」に畳む

    def __post_init__(self) -> None:
        kind = _PY_TYPES.get(self.type, self.type)
        if self.choices is not None:
            kind = "choice"
            object.__setattr__(self, "choices", tuple(self.choices))
        if kind not in PARAM_KINDS:
            raise ValueError(f"未対応のパラメータ型: {self.type!r}（{self.name}）")
        object.__setattr__(self, "type", kind)
        if self.default is not None:
            object.__setattr__(self, "default", self.coerce(self.default))

    # -------------------------------------------------- 値の変換
    def coerce(self, value: Any) -> Any:
        """CLI の文字列や Web の JSON 値を、この型の値に変換する。

        変換できなければ InputError。None と空文字は「未指定」= None。
        """
        if value is None or (isinstance(value, str) and value.strip() == "" and self.type != "str"):
            return None
        try:
            v = self._convert(value)
        except (TypeError, ValueError) as exc:
            raise InputError(f"パラメータ {self.name} の値が不正です: {value!r}（{exc}）") from exc
        self._check_bounds(v)
        return v

    def _convert(self, value: Any) -> Any:
        t = self.type
        if t == "int":
            if isinstance(value, bool):
                raise ValueError("整数を指定してください")
            f = float(value)
            if not f.is_integer():
                raise ValueError("整数を指定してください")
            return int(f)
        if t == "float":
            if isinstance(value, bool):
                raise ValueError("数値を指定してください")
            return float(value)
        if t == "str":
            return str(value)
        if t == "bool":
            if isinstance(value, bool):
                return value
            s = str(value).strip().lower()
            if s in ("1", "true", "yes", "on"):
                return True
            if s in ("0", "false", "no", "off"):
                return False
            raise ValueError("true / false を指定してください")
        if t == "choice":
            s = str(value)
            if s not in (self.choices or ()):
                raise ValueError(f"候補: {', '.join(self.choices or ())}")
            return s
        if t == "range":
            return parse_range(value)
        if t == "json":
            if isinstance(value, str):
                return json.loads(value)
            json.dumps(value)   # JSON にできることを確かめる
            return value
        raise ValueError(t)

    def _check_bounds(self, v: Any) -> None:
        if self.type not in ("int", "float"):
            return
        if self.min is not None and v < self.min:
            raise InputError(f"パラメータ {self.name} は {self.min} 以上にしてください: {v}")
        if self.max is not None and v > self.max:
            raise InputError(f"パラメータ {self.name} は {self.max} 以下にしてください: {v}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "type": self.type, "default": self.default,
            "help": self.help, "label": self.label or self.name, "unit": self.unit,
            "choices": list(self.choices) if self.choices else None,
            "min": self.min, "max": self.max,
            "group": self.group, "advanced": self.advanced,
        }


def parse_range(value: Any) -> list[float | None] | None:
    """``"526,538"`` / ``",538"`` / ``[526, 538]`` を ``[下限, 上限]`` にする。"""
    if value is None:
        return None
    if isinstance(value, str):
        parts: list[Any] = value.split(",")
    else:
        parts = list(value)
    if len(parts) != 2:
        raise ValueError("'下限,上限' の形で指定してください（片側は空でよい）")
    out = [None if (p is None or str(p).strip() == "") else float(p) for p in parts]
    if out == [None, None]:
        return None
    return out


@dataclass(frozen=True)
class FileInput:
    """入力ファイルの定義。

    accept は拡張子のリスト（小文字、例 [".txt", ".csv"]）。空なら何でも受け付ける。
    multiple=True なら複数ファイル（フォルダ単位の入力も可）。
    """

    name: str
    accept: tuple[str, ...] = ()
    multiple: bool = False
    required: bool = True
    help: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "accept", tuple(a.lower() for a in self.accept))

    def accepts(self, filename: str) -> bool:
        return not self.accept or PurePosixPath(filename).suffix.lower() in self.accept

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "accept": list(self.accept), "multiple": self.multiple,
                "required": self.required, "help": self.help}


@dataclass(frozen=True)
class Tool:
    """ツールの宣言的な定義。

    web=False なら CLI 専用（判断基準は docs/design.md）。packages は Pyodide で
    読み込む追加パッケージ。plots=True のツールは図を成果物として出すので、Web では
    matplotlib も読み込む。examples は ``--help`` とドキュメントに載せる実行例。
    """

    name: str
    summary: str
    description: str = ""
    inputs: tuple[FileInput, ...] = ()
    params: tuple[Param, ...] = ()
    web: bool = True
    packages: tuple[str, ...] = ()
    plots: bool = False
    examples: tuple[str, ...] = ()
    cli_only_reason: str = ""

    def __post_init__(self) -> None:
        for attr in ("inputs", "params", "packages", "examples"):
            object.__setattr__(self, attr, tuple(getattr(self, attr)))
        names = [p.name for p in self.params] + [i.name for i in self.inputs]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise ValueError(f"{self.name}: 名前が重複しています: {sorted(dup)}")

    def param(self, name: str) -> Param:
        for p in self.params:
            if p.name == name:
                return p
        raise KeyError(name)

    def web_packages(self) -> list[str]:
        pk = list(self.packages)
        if self.plots and "matplotlib" not in pk:
            pk.append("matplotlib")
        return pk

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "summary": self.summary, "description": self.description,
            "inputs": [i.to_dict() for i in self.inputs],
            "params": [p.to_dict() for p in self.params],
            "web": self.web, "packages": self.web_packages(), "plots": self.plots,
            "examples": list(self.examples), "cli_only_reason": self.cli_only_reason,
        }


# ============================================================ 入力と結果
@dataclass(frozen=True)
class InputFile:
    """入力ファイル1つ（ファイル名と内容）。name はファイル名だけ（フォルダは含めない）。"""

    name: str
    data: bytes

    @property
    def stem(self) -> str:
        return PurePosixPath(self.name).stem

    @property
    def suffix(self) -> str:
        return PurePosixPath(self.name).suffix.lower()

    def text(self) -> str:
        """文字コードを自動判定して文字列にする（core.tableio.decode_text）。"""
        from .tableio import decode_text
        return decode_text(self.data)


@dataclass
class OutputFile:
    """出力ファイル1つ。path は出力フォルダからの相対パス（/ 区切り）。"""

    path: str
    data: bytes


@dataclass
class Figure:
    """図1枚。spec は Plotly の図の形式（data と layout を持つ dict）。

    export=True の図は、成果物（SVG / PNG / 図のJSON / 図のデータCSV）としても
    出力フォルダに書き出される。False ならプレビューだけ。
    """

    name: str
    spec: dict[str, Any]
    export: bool = True


@dataclass
class Result:
    """run() の戻り値。"""

    files: list[OutputFile] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def add_file(self, path: str, content: bytes | str, *, encoding: str = "utf-8") -> None:
        """出力ファイルを追加する。str なら encoding で bytes にする。"""
        if isinstance(content, str):
            content = content.encode(encoding)
        self.files.append(OutputFile(path=path, data=content))

    def add_figure(self, name: str, spec: dict[str, Any], *, export: bool = True) -> None:
        self.figures.append(Figure(name=name, spec=spec, export=export))

    def log(self, message: str) -> None:
        self.logs.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def inputs_by_name(tool: Tool, files: Iterable[tuple[str, InputFile]]) -> dict[str, list[InputFile]]:
    """(入力名, ファイル) の並びを、入力名ごとのリストにまとめる。"""
    out: dict[str, list[InputFile]] = {i.name: [] for i in tool.inputs}
    for name, f in files:
        out.setdefault(name, []).append(f)
    return out
