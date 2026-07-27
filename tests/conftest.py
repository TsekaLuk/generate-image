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

from generate_image.providers import PROVIDERS, _override_prefix  # noqa: E402

# Every provider knob the CLI reads from the environment. Since `auto` routing
# picks a provider by inspecting which credentials are present, a developer with
# real keys exported would otherwise route differently than CI and see failures
# that have nothing to do with their change.
_PROVIDER_ENV = tuple(
    name
    for p in PROVIDERS.values()
    for name in (p.key_env,
                 f"{_override_prefix(p)}_BASE_URL",
                 f"{_override_prefix(p)}_DEFAULT_MODEL")
) + ("GENIMAGE_PROVIDER", "GENIMAGE_RATIO", "GENIMAGE_OUTPUT_DIR", "GENIMAGE_IMAGE_SIZE")


@pytest.fixture(autouse=True)
def _isolate_provider_env(monkeypatch, tmp_path_factory):
    """Run every test against an empty provider environment.

    Tests that need a credential set it themselves via `monkeypatch.setenv`. This
    closes the three ways a real machine leaks one in: variables exported in the
    ambient shell, a `.env` the CLI's loader walks up from the CWD to find, and
    the legacy `~/.seedream-config.json` ARK_API_KEY migration path.

    `_load_dotenv` itself stays live — the loader is under test — so the stubs go
    on the seams it reads from, which is also what the dotenv tests override.
    """
    from generate_image import cli

    for name in _PROVIDER_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(cli, "_find_dotenv", lambda: None)
    empty_home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: empty_home))
