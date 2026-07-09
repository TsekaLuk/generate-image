"""Provider registry for the generate-image skill.

Each `Provider` is one OpenAI-compatible (or near-compatible) image backend.
`openai` is the official OpenAI Images API (default); `302ai` / `openrouter` /
`siliconflow` are public relays/clouds. Fields group into:

  * routing        — base_url, gen_path, edit_path
  * protocol dialect — size_style (how aspect is requested), edit_style (how
    img2img is shaped). Response shape is normalized in generate.extract_image_bytes.
  * model catalog  — default_model, models (advisory; unknown => warn + send)
  * reliability    — bills_on_failure, supports_idempotency, rpm, max_retries,
    default_concurrency (consumed by reliability.py)

Everything is env-overridable via `resolve_provider()` so a new OpenAI-compatible
provider can be swapped in without code changes. The override prefix is the
provider's key_env minus the trailing "_API_KEY", e.g. for openai (OPENAI_API_KEY):

    OPENAI_BASE_URL=...        # override base_url (point at any compatible relay)
    OPENAI_DEFAULT_MODEL=...   # override default_model
    OPENAI_API_KEY=...         # the credential itself
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass

VALID_EDIT_STYLES = frozenset({"multipart", "chat_image", "image_prompt"})
VALID_SIZE_STYLES = frozenset({"openai", "wxh"})


@dataclass(frozen=True)
class Provider:
    """One image backend + its protocol dialect + reliability policy."""

    name: str
    base_url: str
    key_env: str
    gen_path: str
    edit_path: str | None            # None => no image-to-image support at all
    edit_style: str | None           # how img2img is shaped (see VALID_EDIT_STYLES)
    size_style: str | None           # how aspect/size is requested (see VALID_SIZE_STYLES)
    default_model: str
    models: frozenset[str]           # advisory catalog; unknown model => warn + send
    background_unsupported: frozenset[str]  # models where --background is hard-refused
    bills_on_failure: bool           # gateway charges even for failed generations
    supports_idempotency: bool       # honors Idempotency-Key so retries dedupe
    rpm: int                         # client-side token-bucket rate (requests/minute)
    max_retries: int                 # per-provider retry attempt cap
    default_concurrency: int         # starting concurrency for batch mode
    max_ref_images: int              # how many --ref images img2img accepts (0 = no edit)
    supports_seed: bool              # honors a `seed` param for reproducible output


# --- aspect ratio -> size string ----------------------------------------------
# OpenAI-family `size` param (WxH). On the official OpenAI Images API the `size`
# param IS honored: gpt-image models accept 1024x1024, 1536x1024 (landscape) and
# 1024x1536 (portrait), so each ratio below maps to the closest supported size.
# Independently of `size`, the CLI also appends a ratio hint to the prompt
# (cli.RATIO_HINT). That hint is what steers aspect on providers that take no
# size parameter at all (e.g. openrouter, size_style=None), and it is a harmless
# extra steer on providers that do honor `size`. Relays that proxy gpt-image
# behind an OpenAI-compatible surface may ignore `size`; the prompt hint keeps
# aspect control working there too.
OPENAI_RATIO_SIZE = {
    "1:1": "1024x1024",
    "16:9": "1536x1024", "21:9": "1536x1024", "3:2": "1536x1024",
    "4:3": "1536x1024", "5:4": "1536x1024",
    "9:16": "1024x1536", "2:3": "1024x1536", "3:4": "1024x1536", "4:5": "1024x1536",
}
# SiliconFlow `image_size` param (WxH) — REQUIRED and actually honored. Values must
# come from SiliconFlow's supported set; these are the closest match per ratio.
SILICONFLOW_RATIO_SIZE = {
    "1:1": "1328x1328",
    "16:9": "1664x928", "21:9": "1664x928",
    "9:16": "928x1664",
    "3:2": "1584x1056", "4:3": "1024x768",
    "2:3": "1056x1584", "3:4": "768x1024",
    "5:4": "1472x1140", "4:5": "1140x1472",
}


PROVIDERS: dict[str, Provider] = {
    "openai": Provider(
        name="openai",
        base_url="https://api.openai.com",
        key_env="OPENAI_API_KEY",
        gen_path="/v1/images/generations",
        edit_path="/v1/images/edits",
        edit_style="multipart",
        size_style="openai",
        default_model="gpt-image-2",
        models=frozenset({"gpt-image-2", "gpt-image-1"}),
        background_unsupported=frozenset(),  # official API supports background=transparent
        bills_on_failure=False,  # official API does not bill failed requests
        supports_idempotency=False,
        rpm=60,
        max_retries=3,
        default_concurrency=3,
        max_ref_images=16,  # OpenAI gpt-image edits accept up to 16 image[] parts
        supports_seed=False,  # gpt-image has no seed param
    ),
    "302ai": Provider(
        name="302ai",
        base_url="https://api.302.ai",
        key_env="AI302_API_KEY",
        gen_path="/v1/images/generations",
        edit_path="/v1/images/edits",
        edit_style="multipart",
        size_style="openai",
        default_model="gpt-image-2",
        models=frozenset({
            "gpt-image-2", "gpt-image-1",
            "flux-kontext-pro", "flux-kontext-max",
        }),
        background_unsupported=frozenset(),
        bills_on_failure=True,
        supports_idempotency=True,
        rpm=60,
        max_retries=3,
        default_concurrency=3,
        max_ref_images=16,  # gpt-image edits (aggregated)
        supports_seed=False,  # gpt-image relay ignores seed
    ),
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api",
        key_env="OPENROUTER_API_KEY",
        gen_path="/v1/images",  # NOTE: no /generations suffix on OpenRouter
        edit_path="/v1/chat/completions",  # img2img via chat image_url
        edit_style="chat_image",
        size_style=None,  # no size param; aspect steered by prompt hint only
        default_model="google/gemini-2.5-flash-image",
        models=frozenset({
            "google/gemini-2.5-flash-image",
            "bytedance-seed/seedream-4.5",
        }),
        background_unsupported=frozenset(),
        bills_on_failure=False,  # rejected requests are not billed
        supports_idempotency=False,
        rpm=120,
        max_retries=4,
        default_concurrency=4,
        max_ref_images=8,  # chat image_url parts; actual limit varies by model
        supports_seed=False,  # /v1/images has no seed param
    ),
    "siliconflow": Provider(
        name="siliconflow",
        base_url="https://api.siliconflow.cn",
        key_env="SILICONFLOW_API_KEY",
        gen_path="/v1/images/generations",
        edit_path="/v1/images/generations",  # img2img via image_prompt on same endpoint
        edit_style="image_prompt",
        size_style="wxh",  # image_size "WxH" is REQUIRED
        default_model="Qwen/Qwen-Image",
        models=frozenset({
            "Qwen/Qwen-Image",
            "black-forest-labs/FLUX.1-schnell",
            "black-forest-labs/FLUX.1-dev",
            "black-forest-labs/FLUX.1-Kontext-pro",
        }),
        background_unsupported=frozenset(),
        bills_on_failure=False,
        supports_idempotency=False,
        rpm=120,
        max_retries=4,
        default_concurrency=4,
        max_ref_images=1,  # image gen endpoint takes a single input image
        supports_seed=True,  # image_size endpoint accepts a reproducible seed
    ),
}

DEFAULT_PROVIDER = "openai"


def _override_prefix(provider: Provider) -> str:
    """Env-var prefix for overrides: key_env without the trailing '_API_KEY'.

    e.g. OPENAI_API_KEY -> OPENAI, AI302_API_KEY -> AI302, OPENROUTER_API_KEY -> OPENROUTER.
    """
    return provider.key_env.removesuffix("_API_KEY")


def resolve_provider(name: str) -> Provider:
    """Return the Provider for `name` with base_url / default_model applied from
    env overrides (`{PREFIX}_BASE_URL`, `{PREFIX}_DEFAULT_MODEL`).

    Raises KeyError for an unknown provider name.
    """
    if name not in PROVIDERS:
        raise KeyError(f"unknown provider {name!r}; known: {sorted(PROVIDERS)}")
    p = PROVIDERS[name]
    prefix = _override_prefix(p)
    base_url = os.environ.get(f"{prefix}_BASE_URL", p.base_url).rstrip("/")
    default_model = os.environ.get(f"{prefix}_DEFAULT_MODEL", p.default_model)
    return dataclasses.replace(p, base_url=base_url, default_model=default_model)


def ratio_to_size(provider: Provider, ratio: str) -> str | None:
    """Map an aspect ratio to the provider's size string, or None if the provider
    takes no size parameter (aspect is steered by a prompt hint instead)."""
    if provider.size_style == "openai":
        return OPENAI_RATIO_SIZE.get(ratio, "1024x1024")
    if provider.size_style == "wxh":
        return SILICONFLOW_RATIO_SIZE.get(ratio, "1328x1328")
    return None
