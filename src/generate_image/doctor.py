#!/usr/bin/env python3
"""`generate-image-doctor` — a free, no-network diagnostic for the registry.

Reports, for every provider, whether its API key is configured (resolved via the
SAME .env loader the CLI uses), plus its base_url, img2img support, and default
model — so a fresh checkout can tell at a glance what it can actually call before
spending a cent. The default run makes NO billed/network request; it only reads
env + the registry.

  generate-image-doctor            # key/config report, no network, free
  generate-image-doctor --probe    # ONE real 1:1 gen per keyed provider (billed!)

Key VALUES are never printed — only SET / MISSING status. `--probe` is the only
path that touches the network (and money): it confirms each configured key works
end-to-end by generating a single 1:1 image and reporting the decoded dims.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import cli
from .probe import image_dims
from .providers import PROVIDERS, DEFAULT_PROVIDER, resolve_provider
from .reliability import ProviderError

_PROBE_PROMPT = "a single flat minimalist red circle centered on a plain white background, vector"


def _key_is_set(key_env: str) -> bool:
    """True when the provider's key env resolves to a non-empty value.

    Never returns or logs the value itself — only presence.
    """
    return bool(os.environ.get(key_env, "").strip())


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="generate-image-doctor",
        description="Diagnose provider keys/config (free, no network). "
                    "Use --probe for a billed end-to-end check.",
    )
    ap.add_argument(
        "--probe", action="store_true",
        help="for each provider WITH a key, do ONE real 1:1 generate to confirm "
             "the credential works end-to-end (BILLED — one image per provider).",
    )
    ap.add_argument("--timeout", type=int, default=240,
                    help="per-probe HTTP read timeout in seconds (default: 240)")
    return ap.parse_args(argv)


def _report_config(keyed: dict[str, bool]) -> None:
    """Print the per-provider key/config table to stdout; fill `keyed` in place."""
    print(f"generate-image doctor — {len(PROVIDERS)} providers "
          f"(default: {DEFAULT_PROVIDER})\n")
    for name, base in PROVIDERS.items():
        p = resolve_provider(name)  # reflect {PREFIX}_BASE_URL / _DEFAULT_MODEL overrides
        has_key = _key_is_set(p.key_env)
        keyed[name] = has_key
        tag = "  (default)" if name == DEFAULT_PROVIDER else ""
        status = "SET" if has_key else "MISSING"
        img2img = base.edit_style if base.edit_path else "none"
        print(f"■ {name}{tag}")
        print(f"    base_url  : {p.base_url}")
        print(f"    key env   : {p.key_env}")
        print(f"    key status: {status}")
        print(f"    img2img   : {img2img}")
        print(f"    model     : {p.default_model}")
        print()


def _print_summary(keyed: dict[str, bool]) -> None:
    """Print the 'N/<total> providers have a key configured' line + default hint."""
    have = sum(1 for ok in keyed.values() if ok)
    print(f"{have}/{len(PROVIDERS)} providers have a key configured")

    if not keyed.get(DEFAULT_PROVIDER, False):
        dp = PROVIDERS[DEFAULT_PROVIDER]
        print(
            f"\nhint: the DEFAULT provider ({DEFAULT_PROVIDER}) has NO key — image "
            f"generation will fail out of the box.\n"
            f"  Set {dp.key_env}=... in a .env at the project root (see .env.example) "
            f"or export it in your shell."
        )


def _run_probes(keyed: dict[str, bool], timeout: int) -> int:
    """For each provider with a key, do ONE real billed 1:1 generate.

    Returns the number of probes that FAILED so the caller can set a non-zero exit
    code (scriptability: `generate-image-doctor --probe && …` must not report
    success when a credential is broken)."""
    targets = [name for name, ok in keyed.items() if ok]
    if not targets:
        print("\n--probe: no providers have a key configured — nothing to probe.")
        return 0

    est = cli._cost_phrase({n: 1 for n in targets})
    print(
        f"\n--probe: about to make {len(targets)} REAL billed 1:1 generation(s) "
        f"({', '.join(targets)}).\n  Estimated cost: {est}. "
        f"Some relays bill on success AND failure.",
        file=sys.stderr,
    )

    failures = 0
    client = cli.make_client(timeout)
    try:
        for name in targets:
            provider = resolve_provider(name)
            model = provider.default_model
            key = os.environ.get(provider.key_env, "").strip()
            try:
                raw = cli.provider_generate(provider, _PROBE_PROMPT, model, "1:1", key, client)
            except ProviderError as e:
                print(f"■ {name:12} PROBE FAIL — {e}")
                failures += 1
                continue
            except Exception as e:  # noqa: BLE001 - diagnostic must never crash mid-sweep
                print(f"■ {name:12} PROBE FAIL — {type(e).__name__}: {e}")
                failures += 1
                continue
            w, h, fmt = image_dims(raw)
            if not h:
                print(f"■ {name:12} PROBE OK   — {fmt}, {len(raw) // 1024} KB "
                      f"(dims unreadable)")
            else:
                print(f"■ {name:12} PROBE OK   — {w}x{h} {fmt}")
    finally:
        client.close()
    return failures


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    # Resolve keys the same way the CLI does: load the .env, then read os.environ.
    cli._load_dotenv()

    keyed: dict[str, bool] = {}
    _report_config(keyed)
    _print_summary(keyed)

    if args.probe:
        failures = _run_probes(keyed, args.timeout)
        if failures:
            # Non-zero exit so a broken credential fails scripts/CI, matching the
            # main CLI's convention of exiting 1 on generation failure.
            sys.exit(1)


if __name__ == "__main__":
    main()
