"""Shared pytest fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def q4_xml() -> bytes:
    return (FIXTURES / "q4_2025_info_table.xml").read_bytes()


@pytest.fixture
def q3_xml() -> bytes:
    return (FIXTURES / "q3_2025_info_table.xml").read_bytes()
