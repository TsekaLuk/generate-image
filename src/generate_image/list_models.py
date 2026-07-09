#!/usr/bin/env python3
"""List the providers in the registry and each one's models / key env.

The registry (providers.py) is the source of truth. `models` is an advisory
catalog — providers evolve their offerings, so an unknown `-m` model is sent
anyway (with a warning). The starred model is the provider's default.
"""

from __future__ import annotations

from .providers import PROVIDERS, DEFAULT_PROVIDER


def main() -> None:
    print(f"generate-image — {len(PROVIDERS)} providers "
          f"(default: {DEFAULT_PROVIDER})\n")
    for name, p in PROVIDERS.items():
        tag = "  (default)" if name == DEFAULT_PROVIDER else ""
        edits = p.edit_style if p.edit_path else "none"
        print(f"■ {name}{tag}")
        print(f"    base_url : {p.base_url}")
        print(f"    key env  : {p.key_env}")
        print(f"    img2img  : {edits}")
        for m in sorted(p.models):
            marker = "★" if m == p.default_model else " "
            print(f"    {marker} {m}")
        print()


if __name__ == "__main__":
    main()
