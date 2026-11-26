#!/usr/bin/env python3
"""Empirically probe ANY provider's real image behavior.

Answers, with hard data, questions the docs can only claim:
  * does the provider honor the size param, or is total resolution fixed?
  * what is the native resolution / megapixel budget?
  * does `-r` actually control the aspect ratio, and how exactly?

It drives the REAL `provider_generate` path, so each provider's own dialect is
exercised (openai/302 = OpenAI `size`; openrouter = /v1/images; siliconflow =
`image_size`; volcengine = Ark `size: 2K`), and reports the actual pixel dimensions decoded from the returned
image. Generic across the whole registry — not tied to any one provider.

Usage:
  generate-image-probe                       # default provider (openai), a ratio sweep
  generate-image-probe -p siliconflow        # probe another provider
  generate-image-probe -p openai --ratios 1:1,16:9,21:9
  generate-image-probe -p 302ai -m gpt-image-2 --prompt "a red circle"

Each probe is a REAL billed image call — keep the ratio list short.
"""

from __future__ import annotations

import argparse
import struct
import sys

from .providers import PROVIDERS, DEFAULT_PROVIDER, resolve_provider
from .reliability import ProviderError
from . import cli

DEFAULT_RATIOS = "1:1,16:9,9:16,21:9,3:4"
DEFAULT_PROMPT = "a single flat minimalist red circle centered on a plain white background, vector"


def image_dims(b: bytes) -> tuple[int, int, str]:
    """(width, height, format) from a PNG, JPEG or GIF byte string; (0,0,'?') otherwise."""
    if b[:6] in (b"GIF87a", b"GIF89a") and len(b) >= 10:
        w, h = struct.unpack("<HH", b[6:10])
        return w, h, "GIF"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", b[16:24])
        return w, h, "PNG"
    if b[:2] == b"\xff\xd8":  # JPEG: find a Start-Of-Frame marker
        i = 2
        while i < len(b) - 9:
            if b[i] != 0xFF:
                i += 1
                continue
            m = b[i + 1]
            if m in (0xC0, 0xC1, 0xC2, 0xC3):
                h, w = struct.unpack(">HH", b[i + 5:i + 9])
                return w, h, "JPEG"
            if m == 0xD8 or m == 0xD9 or 0xD0 <= m <= 0xD7:
                i += 2
                continue
            i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]
        return 0, 0, "JPEG?"
    return 0, 0, "?"


def gif_frames(b: bytes) -> list[int]:
    """Per-frame delay in ms of a GIF, one entry per frame; [] if `b` is not a GIF.

    Walks the GIF block structure (no Pillow dependency): every image descriptor is
    one frame, and its delay comes from the Graphic Control Extension before it
    (stored in 1/100 s, 0 when the frame has none). A frame counts only once its
    image data is terminated, so a truncated file returns the COMPLETE frames
    before the cut — a short count is visible instead of raising.
    """
    if b[:6] not in (b"GIF87a", b"GIF89a") or len(b) < 13:
        return []

    def table_len(packed: int) -> int:
        return 3 * (1 << ((packed & 0x07) + 1)) if packed & 0x80 else 0

    def skip_sub_blocks(i: int) -> int:
        while i < len(b):
            size = b[i]
            i += 1 + size
            if size == 0:
                return i if i <= len(b) else -1
        return -1

    frames: list[int] = []
    delay = 0
    i = 13 + table_len(b[10])
    while i < len(b):
        block = b[i]
        if block == 0x3B:                      # trailer
            break
        if block == 0x21 and i + 1 < len(b):   # extension
            if b[i + 1] == 0xF9 and i + 6 < len(b):
                delay = struct.unpack("<H", b[i + 4:i + 6])[0] * 10
            i = skip_sub_blocks(i + 2)
            if i < 0:
                break
            continue
        if block == 0x2C and i + 10 <= len(b):  # image descriptor = one frame
            i = skip_sub_blocks(i + 10 + table_len(b[i + 9]) + 1)
            if i < 0:
                break                          # cut inside this frame: not counted
            frames.append(delay)
            delay = 0
            continue
        break
    return frames


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Probe a provider's real size/aspect behavior (billed calls).")
    ap.add_argument("-p", "--provider", choices=list(PROVIDERS), default=DEFAULT_PROVIDER)
    ap.add_argument("-m", "--model", default=None, help="model id (default: provider's)")
    ap.add_argument("--ratios", default=DEFAULT_RATIOS,
                    help=f"comma-separated ratios to probe (default: {DEFAULT_RATIOS})")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--timeout", type=int, default=240)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    provider = resolve_provider(args.provider)
    model = args.model or provider.default_model
    ratios = [r.strip() for r in args.ratios.split(",") if r.strip()]

    key = cli.require_key(provider.key_env)
    client = cli.make_client(args.timeout)

    print(f"probing {provider.name} / {model}", file=sys.stderr)
    print(f"  base={provider.base_url}  gen_path={provider.gen_path}  "
          f"size_style={provider.size_style}", file=sys.stderr)
    print(f"  (each row is one real billed call)\n", file=sys.stderr)

    areas: list[float] = []
    try:
        for ratio in ratios:
            if ratio not in cli.VALID_RATIOS:
                print(f"  -r {ratio:6} -> skipped (not a valid ratio)")
                continue
            try:
                raw = cli.provider_generate(provider, args.prompt, model, ratio, key, client)
            except ProviderError as e:
                print(f"  -r {ratio:6} -> ERROR {e}")
                continue
            w, h, fmt = image_dims(raw)
            if not h:
                print(f"  -r {ratio:6} -> {fmt} (could not read dims, {len(raw) // 1024} KB)")
                continue
            mp = w * h / 1e6
            areas.append(mp)
            aspect = round(w / h, 3)
            print(f"  -r {ratio:6} -> {w}x{h:<5} {fmt}  ({mp:.2f} MP, aspect {aspect})")
    finally:
        client.close()

    if len(areas) >= 2:
        lo, hi = min(areas), max(areas)
        verdict = "FIXED area (size ignored)" if (hi - lo) / hi < 0.05 else "size honored / variable"
        print(f"\nverdict: {verdict} — area {lo:.2f}..{hi:.2f} MP across {len(areas)} ratios",
              file=sys.stderr)


if __name__ == "__main__":
    main()
