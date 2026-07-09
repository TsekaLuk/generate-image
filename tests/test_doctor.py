"""`generate-image-doctor` diagnostics, driven through doctor.main().

The default path must NEVER hit the network and must NEVER print a key value —
it only reads env (via the CLI's own .env loader) + the registry. We control the
key state by monkeypatching os.environ AND stubbing the .env loader to a no-op so
a real project .env can't leak keys into the report.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from generate_image import cli
from generate_image import doctor
from generate_image.providers import PROVIDERS, DEFAULT_PROVIDER

# A real 1x1 PNG so probe.image_dims() decodes width/height = 1/1.
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

_ALL_KEY_ENVS = [p.key_env for p in PROVIDERS.values()]


@pytest.fixture(autouse=True)
def _no_real_dotenv(monkeypatch):
    """Never load the on-disk .env — the test controls key state explicitly."""
    monkeypatch.setattr(cli, "_load_dotenv", lambda: None)


def _clear_all_keys(monkeypatch):
    for env in _ALL_KEY_ENVS:
        monkeypatch.delenv(env, raising=False)


def test_default_run_reports_missing_and_summary(monkeypatch, capsys):
    _clear_all_keys(monkeypatch)

    doctor.main([])

    out = capsys.readouterr().out
    # Every provider present, all MISSING, summary counts zero.
    for name in PROVIDERS:
        assert f"■ {name}" in out
    assert "key status: MISSING" in out
    assert "key status: SET" not in out
    assert f"0/{len(PROVIDERS)} providers have a key configured" in out


def test_default_provider_missing_prints_hint(monkeypatch, capsys):
    _clear_all_keys(monkeypatch)

    doctor.main([])

    out = capsys.readouterr().out
    assert PROVIDERS[DEFAULT_PROVIDER].key_env in out  # OPENAI_API_KEY
    assert "hint:" in out
    assert ".env.example" in out


def test_some_keys_set_counts_and_no_hint(monkeypatch, capsys):
    _clear_all_keys(monkeypatch)
    # Default (openai) + one more get a key.
    monkeypatch.setenv(PROVIDERS[DEFAULT_PROVIDER].key_env, "test-key-not-real")
    monkeypatch.setenv(PROVIDERS["302ai"].key_env, "another-test-key")

    doctor.main([])

    out = capsys.readouterr().out
    assert f"2/{len(PROVIDERS)} providers have a key configured" in out
    assert "key status: SET" in out
    # Default is keyed -> no rename hint.
    assert "hint:" not in out


def test_key_value_is_never_printed(monkeypatch, capsys):
    _clear_all_keys(monkeypatch)
    secret = "sk-SUPER-SECRET-VALUE-12345"
    monkeypatch.setenv(PROVIDERS[DEFAULT_PROVIDER].key_env, secret)

    doctor.main([])

    combined = capsys.readouterr()
    assert secret not in combined.out
    assert secret not in combined.err


def test_default_path_makes_no_network(monkeypatch, capsys):
    _clear_all_keys(monkeypatch)
    monkeypatch.setenv(PROVIDERS[DEFAULT_PROVIDER].key_env, "test-key-not-real")

    def handler(req):  # pragma: no cover - must never be reached
        raise AssertionError("doctor default path must not hit the network")

    monkeypatch.setattr(cli, "_TEST_TRANSPORT", httpx.MockTransport(handler))

    doctor.main([])  # no --probe: no network

    out = capsys.readouterr().out
    assert "providers have a key configured" in out


def test_probe_only_hits_keyed_providers(monkeypatch, capsys):
    _clear_all_keys(monkeypatch)
    monkeypatch.setenv(PROVIDERS[DEFAULT_PROVIDER].key_env, "test-key-not-real")

    calls: list[str] = []

    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(
            200, json={"data": [{"b64_json": base64.b64encode(_TINY_PNG).decode("ascii")}]}
        )

    monkeypatch.setattr(cli, "_TEST_TRANSPORT", httpx.MockTransport(handler))

    doctor.main(["--probe"])

    out = capsys.readouterr().out
    assert "PROBE OK" in out
    assert "1x1" in out
    # Exactly one keyed provider -> exactly one billed call.
    assert len(calls) == 1


def test_probe_with_no_keys_makes_no_call(monkeypatch, capsys):
    _clear_all_keys(monkeypatch)

    def handler(req):  # pragma: no cover - must never be reached
        raise AssertionError("no keyed providers -> no probe calls")

    monkeypatch.setattr(cli, "_TEST_TRANSPORT", httpx.MockTransport(handler))

    doctor.main(["--probe"])

    out = capsys.readouterr().out
    assert "nothing to probe" in out


def test_probe_reports_provider_error(monkeypatch, capsys):
    _clear_all_keys(monkeypatch)
    monkeypatch.setenv(PROVIDERS[DEFAULT_PROVIDER].key_env, "test-key-not-real")

    def handler(req):
        return httpx.Response(401, json={"error": "bad key"})

    monkeypatch.setattr(cli, "_TEST_TRANSPORT", httpx.MockTransport(handler))

    # A failed probe must exit non-zero (scriptability), while still printing the
    # PROBE FAIL line.
    with pytest.raises(SystemExit) as ei:
        doctor.main(["--probe"])
    assert ei.value.code not in (0, None)

    out = capsys.readouterr().out
    assert "PROBE FAIL" in out


def test_probe_all_ok_exits_zero(monkeypatch, capsys):
    _clear_all_keys(monkeypatch)
    monkeypatch.setenv(PROVIDERS[DEFAULT_PROVIDER].key_env, "test-key-not-real")

    def handler(req):
        return httpx.Response(
            200, json={"data": [{"b64_json": base64.b64encode(_TINY_PNG).decode("ascii")}]}
        )

    monkeypatch.setattr(cli, "_TEST_TRANSPORT", httpx.MockTransport(handler))

    doctor.main(["--probe"])  # all probes succeed -> no SystemExit
    assert "PROBE OK" in capsys.readouterr().out
