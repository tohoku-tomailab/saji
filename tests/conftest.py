from __future__ import annotations

from pathlib import Path

import pytest

from saji.core.tool import InputFile

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = Path(__file__).parent / "golden"


def load_input(path: Path) -> InputFile:
    return InputFile(name=path.name, data=path.read_bytes())


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def golden() -> Path:
    return GOLDEN
