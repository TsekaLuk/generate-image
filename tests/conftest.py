"""Pytest configuration for the generate-image test suite.

The code lives in the `generate_image` package under `src/`. Put `src/` on
sys.path so a bare `pytest` run works without an editable install (under
`uv run pytest` the package is already installed, and this is a harmless no-op).
Tests import the package modules, aliasing the CLI module as `generate`:

    from generate_image import cli as generate
    from generate_image import providers, dag, reliability
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from generate_image.providers import PROVIDERS  # noqa: E402


@pytest.fixture(autouse=True)
def _hermetic_provider_env(monkeypatch):
    """Strip ambient provider env overrides so tests never depend on the shell.

    OPENAI_BASE_URL / OPENAI_API_KEY are commonly exported in developer shells;
    without this, resolve_provider() would silently point the default provider at
    whatever relay the developer uses and break the mocked-transport assertions.
    """
    for p in PROVIDERS.values():
        prefix = p.key_env.removesuffix("_API_KEY")
        monkeypatch.delenv(p.key_env, raising=False)
        monkeypatch.delenv(f"{prefix}_BASE_URL", raising=False)
        monkeypatch.delenv(f"{prefix}_DEFAULT_MODEL", raising=False)
