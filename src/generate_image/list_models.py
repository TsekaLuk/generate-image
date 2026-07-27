#!/usr/bin/env python3
"""List the providers in the registry and each one's models / key env.

The registry (providers.py) is the source of truth. `models` is an advisory
catalog — providers evolve their offerings, so an unknown `-m` model is sent
anyway (with a warning). The starred model is the provider's default.
"""

from __future__ import annotations

from .providers import PROVIDERS, AUTO_PROVIDER, ROUTER_PRIORITY


def main() -> None:
    print(f"generate-image — {len(PROVIDERS)} providers "
          f"(default: {AUTO_PROVIDER})\n")
    for name, p in PROVIDERS.items():
        # A provider missing from ROUTER_PRIORITY is unreachable via `auto`, which is
        # worth showing rather than crashing the listing on a lookup.
        rank = ROUTER_PRIORITY.index(name) + 1 if name in ROUTER_PRIORITY else None
        tag = f"  (auto priority {rank})" if rank else "  (not routed by auto)"
        edits = p.edit_style if p.edit_path else "none"
        print(f"■ {name}{tag}")
        print(f"    base_url : {p.base_url}")
        print(f"    key env  : {p.key_env}")
        print(f"    img2img  : {edits}")
        for prefix, ov in p.model_dialects:
            # A gateway fronting several upstream protocols: say so, otherwise the
            # single img2img line above reads as if it applied to every model.
            print(f"    note     : {prefix}* models use a different dialect "
                  f"({ov.get('gen_path', p.gen_path)}, "
                  f"img2img {ov.get('edit_style', edits)})")
        for m in sorted(p.models):
            marker = "★" if m == p.default_model else " "
            print(f"    {marker} {m}")
        print()


if __name__ == "__main__":
    main()
