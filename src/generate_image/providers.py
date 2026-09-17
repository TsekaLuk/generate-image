"""Provider registry for the generate-image skill.

Each `Provider` is one OpenAI-compatible (or near-compatible) image backend.
`openai` is the official OpenAI Images API (default); `302ai` / `openrouter` /
`siliconflow` / `volcengine` / `147ai` are public relays/clouds. Fields group into:

  * routing        — base_url, gen_path, edit_path
  * protocol dialect — size_style (how aspect is requested), edit_style (how
    img2img is shaped). Response shape is normalized in generate.extract_image_bytes.
  * model catalog  — default_model, models (advisory; unknown => warn + send),
    plus model_dialects for gateways that front several upstream protocols on one
    base_url (147ai: Gemini via chat/completions, gpt-image via /v1/images/*)
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

VALID_GEN_STYLES = frozenset({"openai", "ark", "chat_image_config"})
VALID_EDIT_STYLES = frozenset({
    "multipart", "chat_image", "image_prompt", "ark_json", "chat_image_config",
    "sensenova_json",
})
VALID_SIZE_STYLES = frozenset({
    "openai", "openai_custom", "wxh", "ark", "image_config", "openai_xl",
    "sensenova",
})
AUTO_PROVIDER = "auto"


@dataclass(frozen=True)
class Provider:
    """One image backend + its protocol dialect + reliability policy."""

    name: str
    base_url: str
    key_env: str
    gen_path: str
    gen_style: str                  # generation request dialect (see VALID_GEN_STYLES)
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
    # Honors the OpenAI `quality` tier for real. Set this ONLY where it holds: a
    # relay can accept the field and change nothing, so you would pay for a tier you
    # never got. 147ai must stay False for a different reason — there the tier rides
    # in the MODEL NAME (gpt-image-2-low/-medium/-high), so a `quality` field would
    # fight the model id.
    supports_quality: bool = False
    # Statuses this gateway uses for a TRANSIENT throttle even though the code
    # normally means something permanent. Retry treats these as retryable. Only add
    # one after observing it clear on its own — see reliability.is_retryable_status.
    throttle_statuses: frozenset[int] = frozenset()
    # Re-issue a request whose CONNECTION broke mid-flight (SSL EOF / reset), even
    # when bills_on_failure and there is no idempotency key. Set this only where the
    # failure is known to be billed anyway, so not retrying costs the same and just
    # loses the image. Read timeouts are unaffected — they stay conservative.
    retry_broken_transport: bool = False
    # Minimum seconds between a failure and its retry. Default 0 keeps standard
    # full-jitter backoff (which can wait ~0s). Raise it where an immediate retry
    # would just reproduce a rate-induced failure.
    backoff_floor: float = 0.0
    # Some gateways front several upstreams with DIFFERENT protocols on one base_url
    # (147ai: Gemini via chat/completions, gpt-image via /v1/images/*). Each entry is
    # (model_prefix, {field: value}) applied by `apply_model_dialect` when the chosen
    # model starts with that prefix. First match wins; empty = one dialect for all.
    model_dialects: tuple[tuple[str, dict], ...] = ()
    # The registered base_url is a placeholder, not a reachable host: the provider is
    # unusable until {PREFIX}_BASE_URL is set. Routing skips such a provider entirely
    # so credentials are never sent to a guessed address.
    requires_base_url: bool = False


# --- quality tiers ------------------------------------------------------------
# gpt-image quality ladder. `low`/`medium`/`high` are the long-standing set;
# GPT Image 2.5 (2026-09-08) added `xhigh` and `max` ABOVE the old ceiling.
VALID_QUALITY_TIERS = ("low", "medium", "high", "xhigh", "max", "auto")
# The two tiers that exist only on 2.5. Listed explicitly rather than sniffed out of
# the model string: `"2.5" in model` would happily pass a future gpt-image-3 that
# does not have them, and the failure would surface as a billed no-op — measured on
# a relay, `xhigh` on gpt-image-2 returns HTTP 200 and simply ignores the tier.
EXTENDED_QUALITY_TIERS = frozenset({"xhigh", "max"})
EXTENDED_QUALITY_MODELS = frozenset({
    "gpt-image-2.5-flare", "gpt-image-2.5-sunburst",
    "gpt-image-2.5", "gpt-image-2.5-dev",
})


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
# Exact-aspect sizes for the gpt-image `size` contract as published by OpenAI
# (2026-09): width and height are multiples of 16, aspect between 1:3 and 3:1,
# neither edge over 3840, total pixels 655,360..8,294,400. `gpt-image-2.5-flare`
# and `-sunburst` accept arbitrary WIDTHxHEIGHT inside that window rather than
# only the three canonical values.
#
# WHY THIS EXISTS: OPENAI_RATIO_SIZE collapses 10 aspect ratios onto 3 sizes, so
# every provider that actually honors `size` received 7 of 10 ratios as the WRONG
# ASPECT — `-r 21:9` went out as 1536x1024 (1.50, not 2.33), `-r 4:3` as 1.50
# (not 1.33), `-r 9:16` as 0.67 (not 0.56). Verified end to end against 302ai
# 2026-09-16: a custom size comes back verbatim (`1792x768` -> 1792x768,
# `2048x2048` -> 2048x2048), and `-r 21:9` now yields 1904x816 (2.333, 0.00% off).
#
# The AREA is deliberately held at ~1.57 MP, the same budget OPENAI_RATIO_SIZE
# already used (1536x1024 = 1,572,864 px): the defect being fixed is the ASPECT,
# not the image being small. Raising the ceiling is a separate, cost-bearing call
# (302ai reaches 4.19 MP at 2048², measured). Entries whose aspect was ALREADY
# correct (1:1, 3:2, 2:3) are kept byte-identical so nothing relying on them moves.
OPENAI_CUSTOM_RATIO_SIZE = {
    "1:1": "1024x1024",      # unchanged (aspect was already exact)
    "3:2": "1536x1024",      # unchanged
    "2:3": "1024x1536",      # unchanged
    "16:9": "1680x944",      # was 1536x1024 (1.50) -> now 1.780, target 1.778
    "9:16": "944x1680",      # was 1024x1536 (0.67) -> now 0.562, target 0.563
    "21:9": "1904x816",      # was 1536x1024 (1.50) -> now 2.333, target 2.333
    "4:3": "1456x1088",      # was 1536x1024 (1.50) -> now 1.338, target 1.333
    "3:4": "1088x1456",      # was 1024x1536 (0.67) -> now 0.747, target 0.750
    "5:4": "1408x1120",      # was 1536x1024 (1.50) -> now 1.257, target 1.250
    "4:5": "1136x1424",      # was 1024x1536 (0.67) -> now 0.798, target 0.800
}

# Google `image_config.image_size` tiers (147ai). Unlike every other provider here
# this is a resolution TIER, not a WxH string, and it is honored for real — so this
# is the one route to true 4K in this skill (the OpenAI `size` enum tops out at
# 1536x1024, i.e. ~1.57 MP).
IMAGE_CONFIG_SIZES = ("1K", "2K", "4K")
DEFAULT_IMAGE_CONFIG_SIZE = "2K"
# 147ai's gpt-image-2 line accepts a LARGER `size` enum than the stock OpenAI set
# (documented: auto, 1024², 1536x1024, 1024x1536, 2048², 2048x1152, 1152x2048,
# 3072x1024, 1024x3072). Ratios without an exact member fall back to the closest
# orientation match rather than silently squaring the image.
OPENAI_XL_RATIO_SIZE = {
    "1:1": "2048x2048",
    "16:9": "2048x1152", "9:16": "1152x2048",
    "21:9": "3072x1024", "9:21": "1024x3072",
    "3:2": "1536x1024", "2:3": "1024x1536",
    "4:3": "1536x1024", "3:4": "1024x1536",
    "5:4": "2048x1152", "4:5": "1152x2048",
}
# SenseNova `size`. Per the vendor API doc (effective 2026-09-15), u1-pro and
# u1.5-lite take an ARBITRARY WIDTHxHEIGHT, not a fixed enum:
#   * width and height must be multiples of 32
#   * u1-pro   : 512..8192 per edge, aspect at most 5:1 / 1:5 (8K is experimental)
#   * u1.5-lite: 512..4096 per edge, aspect at most 3:1 / 1:3
#   * "auto" lets the server choose
# The values below sit at the doc's suggested 2K tier (~4.2 MP) and satisfy the
# TIGHTER of the two models' limits, so one table is valid for both.
# 1:1 / 16:9 / 9:16 / 3:2 / 2:3 are exactly the sizes the doc recommends; the rest
# are computed to the same budget because the doc lists no value for them.
#
# ⚠️ An earlier version of this table was a FIXED enum scraped from a 400 response:
#   "field Size invalid, should be one of: 1664x2496, 2496x1664, 1760x2368, ...".
# That enum is real but belongs to `sensenova-u1-fast`, a DIFFERENT model that is
# not in this doc — it was simply the only model the first API key could call.
# Do not reintroduce it for u1-pro / u1.5-lite; those accept the custom sizes here
# (verified: 2752x1536 came back verbatim from u1-pro, and 2752/32 = 86).
SENSENOVA_RATIO_SIZE = {
    "1:1": "2048x2048",      # doc-recommended 2K
    "16:9": "2720x1536",     # doc-recommended
    "9:16": "1536x2720",     # doc-recommended
    "3:2": "2496x1664",      # doc-recommended
    "2:3": "1664x2496",      # doc-recommended
    "4:3": "2336x1760",      # computed, 1.327 vs 1.333 (0.45%)
    "3:4": "1792x2400",      # computed, 0.747 vs 0.750 (0.44%)
    "21:9": "3136x1344",     # computed, 2.333 exact
    "4:5": "1824x2272",      # computed, 0.803 vs 0.800 (0.35%)
    "5:4": "2272x1824",      # computed, 1.246 vs 1.250 (0.35%)
}
# Edge/step rules above, kept next to the table so a future edit can be checked.
SENSENOVA_SIZE_STEP = 32
SENSENOVA_SIZE_MIN = 512
SENSENOVA_SIZE_MAX = 4096        # the tighter (u1.5-lite) cap; u1-pro allows 8192

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
        gen_style="openai",
        edit_path="/v1/images/edits",
        edit_style="multipart",
        # The published gpt-image `size` contract accepts an arbitrary WIDTHxHEIGHT
        # (see OPENAI_CUSTOM_RATIO_SIZE), not just the three canonical values, so
        # the aspect the caller asked for can travel in `size` instead of being
        # rounded to the nearest of three shapes.
        size_style="openai_custom",
        # OpenAI shipped GPT Image 2.5 on 2026-09-08 as two ids: `-flare` (faster,
        # the recommended default) and `-sunburst` (editing precision, slower).
        # Both add two quality tiers above the old ceiling — `xhigh` and `max` —
        # which this CLI does not send; see SKILL.md's parameter matrix for why.
        default_model="gpt-image-2.5-flare",
        models=frozenset({
            "gpt-image-2.5-flare", "gpt-image-2.5-sunburst",
            "gpt-image-2", "gpt-image-1",
        }),
        background_unsupported=frozenset(),  # official API supports background=transparent
        bills_on_failure=False,  # official API does not bill failed requests
        supports_idempotency=False,
        rpm=60,
        max_retries=3,
        default_concurrency=3,
        max_ref_images=16,  # OpenAI gpt-image edits accept up to 16 image[] parts
        supports_seed=False,  # gpt-image has no seed param
        supports_quality=True,  # `quality` is part of the published images contract
    ),
    "302ai": Provider(
        name="302ai",
        base_url="https://api.302.ai",
        key_env="AI302_API_KEY",
        gen_path="/v1/images/generations",
        gen_style="openai",
        edit_path="/v1/images/edits",
        edit_style="multipart",
        # Measured 2026-09-16: this relay honors a custom `size` verbatim
        # (1792x768 and 2048x2048 both came back exactly as asked) and has no
        # ~1.57 MP ceiling — 2048² = 4.19 MP was returned intact.
        size_style="openai_custom",
        # Measured 2026-09-14 (same prompt, 1024², usage-token billing):
        #   gpt-image-2.5-flare     74.3s  196 out-tok  <- default, fastest at its price
        #   gpt-image-2.5-sunburst  91.0s  196 out-tok
        #   gpt-image-2             56.0s  (faster, but pricier per image)
        #   gpt-image-2.5           86.4s 2058 out-tok  (~10x dearer, no quality gain)
        # All of the above are at the relay's DEFAULT quality tier. Measured
        # 2026-09-16, `quality` swings output tokens 36x on this provider
        # (low=196, max=7024) — and the cost table below has no quality dimension,
        # which is exactly why no --quality flag is exposed yet.
        default_model="gpt-image-2.5-flare",
        models=frozenset({
            "gpt-image-2.5-flare", "gpt-image-2.5-sunburst",
            "gpt-image-2.5", "gpt-image-2.5-dev",
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
        # Measured 2026-09-16: quality is honored here — at 1024², output_tokens go
        # low/auto 196 -> medium 439 -> high 1756 -> xhigh 3122 -> max 7024 (35.8x).
        supports_quality=True
    ),
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api",
        key_env="OPENROUTER_API_KEY",
        gen_path="/v1/images",  # NOTE: no /generations suffix on OpenRouter
        gen_style="openai",
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
        gen_style="openai",
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
    "147ai": Provider(
        name="147ai",
        base_url="https://nn.147ai.com",
        key_env="AI147_API_KEY",  # env vars cannot start with a digit (cf. AI302_API_KEY)
        # Gemini-family image models are served through chat/completions, with
        # aspect + resolution carried in extra_body.google.image_config. The same
        # endpoint does text-to-image and image-to-image (refs become image_url
        # content parts), so gen_path == edit_path.
        gen_path="/v1/chat/completions",
        gen_style="chat_image_config",
        edit_path="/v1/chat/completions",
        edit_style="chat_image_config",
        # image_config.image_size is a QUALITY TIER (1K/2K/4K), not WxH; the aspect
        # is a separate honored field, so unlike the stock OpenAI enum this reaches true 4K.
        size_style="image_config",
        default_model="gemini-3-pro-image-preview",
        models=frozenset({
            # Gemini family -> chat/completions + image_config (the provider default)
            "gemini-3-pro-image-preview",
            "gemini-3-pro-image-preview-stable",
            "gemini-3.1-flash-image-preview",
            "gemini-2.5-flash-image",
            "gemini-2.5-flash-image-preview",
            # gpt-image family -> OpenAI /v1/images/* (see model_dialects below).
            # Quality is chosen by the model suffix, not a `quality` param.
            "gpt-image-2-low",
            "gpt-image-2-medium",
            "gpt-image-2-high",
            "gpt-image-2-client",
            "gpt-image-2-client-4K",
        }),
        # One base_url, two protocols: gpt-image-* speaks plain OpenAI images.
        # Its `size` enum reaches 2048x2048 / 3072x1024, well past the stock 1536x1024.
        model_dialects=(
            ("gpt-image-2", {
                "gen_path": "/v1/images/generations",
                "gen_style": "openai",
                "edit_path": "/v1/images/edits",
                "edit_style": "multipart",
                "size_style": "openai_xl",
                "max_ref_images": 16,
            }),
        ),
        background_unsupported=frozenset(),
        # New API debits credits per generation; treat failures as billable so the
        # reliability layer never retries a call that may have completed.
        bills_on_failure=True,
        supports_idempotency=False,
        # Measured 2026-07: back-to-back requests get their TLS connection cut
        # (SSL UNEXPECTED_EOF) — reproducible within ~20s, gone after a cooldown.
        # gpt-image-2 generations also run 50-140s, so pace conservatively.
        rpm=12,
        max_retries=4,
        default_concurrency=1,
        # That SSL EOF is billed regardless, so retrying it is strictly better than
        # paying for nothing. See _transport_retryable in cli.py.
        retry_broken_transport=True,
        # An immediate retry reproduces the cut connection; ~20s was measured clean.
        backoff_floor=20.0,
        max_ref_images=8,  # chat image_url parts; actual ceiling varies by model
        supports_seed=False,  # image_config exposes no seed field
    ),
    "sensenova": Provider(
        name="sensenova",
        # 2026-09-17 实测（真实调用，非文档抄写）：
        #   * base_url + Bearer 鉴权确认可用（GET /v1/models 回 200；
        #     api.sensenova.cn 是 404 "no Route matched"，只有 token. 这个 host 对）。
        #   * /v1/images/generations 走标准 OpenAI 形态，model+prompt+n=1+size 可用。
        #   * 返回体只有 `url`，没有 b64_json —— extract_image_bytes 会去拉取。
        #   * 不发 size 时服务端默认给 2752x1536（即 16:9 那一档）。
        #   * 分辨率约 4.2MP，是本注册表里的高分辨率档（比本注册表其他 provider 都高）。
        base_url="https://token.sensenova.cn",
        key_env="SENSENOVA_API_KEY",
        gen_path="/v1/images/generations",
        gen_style="openai",
        # 图生图：JSON 方言，不是 multipart。请求体形如
        #   {"model": ..., "prompt": ..., "images": [{"image_url": "<公网URL 或
        #    data:image/png;base64,...>"}], "n": 1, "size": ..., ...}
        # 关键点（官方文档，2026-09-15 生效）：字段是复数 `images`，数组里是
        # **对象**且键名是 `image_url`，至多 5 张，第 1 张为主编辑图；
        # image_url 只收公网 http/https 链接或带 `data:image/*;base64,` 前缀的
        # Data URL，**纯裸 base64 不支持**。
        # 历史教训：本 provider 曾被标为"不支持图生图"，因为黑盒试了 11 种形态全败。
        # 事后对照文档才发现两个维度各错一半 —— 试过 images=[裸字符串]、也试过
        # image=[{url:...}]，唯独没试到 images=[{image_url:...}] 这个组合。而网关
        # 对所有错误形态都回同一句 "invalid images, should contain between 1 and 5
        # items"（那只是"一张图都没解析到"的默认提示，连不含 image 字段的请求也报
        # 它），所以报错本身对定位字段名零信息量。
        edit_path="/v1/images/edits",
        edit_style="sensenova_json",
        # `size` 是**真生效的固定枚举**，不是自定义 WxH：非法值直接 400，而那条
        # 400 本身就把合法集合列全了（见 SENSENOVA_RATIO_SIZE 上方注释）。
        size_style="sensenova",
        # ⚠️ **模型可用性按账号变化** —— 别把 default_model 当成"一定能用"。
        # 两把不同的 SenseNova key 实测对比（2026-09-17，同一 base_url）：
        #
        #   模型                  key A                key B
        #   sensenova-u1-pro      间歇 403 限流         ✅ 200  74s 1856x1856 (3.44MP)
        #   sensenova-u1-fast     ✅ 200 7–14s          ❌ 404 model is not found
        #   sensenova-u1.5-lite   ✅ 200 ~143s          ✅ 200 138s 2048x2048 (4.19MP)
        #   /v1/models 目录        8 个模型              只有 2 个
        #
        # 没有哪个模型在两把 key 上都稳，所以这里选不出"永远安全"的默认值。取
        # u1-pro：厂商公告主推的正式版，且在当前配置的 key 上实测可用。
        # **换 key 后若默认模型 404，不用改代码** —— 设
        # SENSENOVA_DEFAULT_MODEL=<你账号里有的模型>，并先用 `generate-image-models`
        # 或 doctor 看自己账号有什么。
        #
        # 两种错误码含义不同，且报文措辞正好相反，实测区分：
        #   404 not_found_error   code 5 "model is not found"
        #       -> 这个账号确实没有该模型。不可重试，换模型。
        #   403 permission_denied code 7 "model is not available in the current
        #       token plan"
        #       -> 读着像"没开通"，实际是**限流**：同 key 同模型，403 是 1–2 秒秒回、
        #          成功要 40–74 秒，冷却约 20 秒后恢复 200（已实测）。故登记进
        #          throttle_statuses 当可重试处理。
        #   一度以为 403 的规律是"带 size 就报"，被对照实验推翻（带 size 成功过、
        #   不带 size 也 403 过）—— 真正的变量是调用节奏。
        #
        # 另：u1-pro **不在 /v1/models 列表里却能调用**，那个目录不完整，
        # 不能拿来判断可用性。
        #
        # 出图特征（key B 实测）：u1-pro 1856x1856 / b64_json；
        # u1.5-lite 2048x2048 / b64_json，但 ~138s 很慢。key A 上的 u1-fast 是
        # 唯一返回 url 形态的，7–14 秒最快、2752x1536。
        default_model="sensenova-u1-pro",
        models=frozenset({
            "sensenova-u1-fast", "sensenova-u1.5-lite", "sensenova-u1-pro",
        }),
        background_unsupported=frozenset(),   # 未实测；厂商未提 background
        # 仍未确认：没有账单面板可核对，故保持保守方向（按失败也计费处理，
        # 让重试更克制）。注意 400 是秒回且未出图，通常不计费。
        # 仍未确认：没有账单面板可核对，故保持保守方向（按失败也计费处理，
        # 让重试更克制）。注意 400/403 都是秒回且未出图，通常不计费。
        bills_on_failure=True,
        supports_idempotency=False,           # 未确认
        # 实测这家对调用节奏很敏感（见 default_model 上方那段 403 说明），
        # 所以并发压到 1、rpm 压低、并给一个退避下限 —— 与 147ai 同样的处置。
        # 背靠背发就是白等：403 秒回，重试太快只会再撞一次。
        rpm=6,
        max_retries=3,
        default_concurrency=1,
        backoff_floor=20.0,
        # 这家把"太快了"说成 403 权限错误。实测它会自己恢复（403 秒回，20 秒后
        # 同 key 同模型 HTTP 200），所以按可重试处理 —— 否则一次限流会变成硬失败。
        throttle_statuses=frozenset({403}),
        max_ref_images=5,                     # 官方文档：images 至多 5 张
        supports_seed=False,                  # 未实测
        supports_quality=False,               # 未实测，绝不臆测计费杠杆
    ),
    "volcengine": Provider(
        name="volcengine",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        key_env="ARK_API_KEY",
        gen_path="/images/generations",
        gen_style="ark",
        edit_path="/images/generations",
        edit_style="ark_json",
        size_style="ark",  # Ark accepts quality tiers such as "2K"; ratio stays prompt-steered
        default_model="doubao-seedream-5-0-260128",
        models=frozenset({
            "doubao-seedream-5-0-lite-260128",
            "doubao-seedream-5-0-260128",
            "doubao-seedream-5-0-pro-260628",
        }),
        background_unsupported=frozenset({
            "doubao-seedream-5-0-lite-260128",
            "doubao-seedream-5-0-260128",
            "doubao-seedream-5-0-pro-260628",
        }),
        # Ark does not document idempotency. Treat ambiguous failures as billable so
        # the reliability layer never retries a potentially completed generation.
        bills_on_failure=True,
        supports_idempotency=False,
        rpm=60,
        max_retries=3,
        default_concurrency=2,
        max_ref_images=10,
        supports_seed=True,
    ),
}

DEFAULT_PROVIDER = "openai"
# Order `auto` prefers when several providers can serve a request equally well.
# The official API first, then the relays, and `147ai` last:
# it is the only route to true 4K but paces at rpm=12 / concurrency=1 with a 20s
# backoff floor, so it should be chosen deliberately rather than by default.
# Every registered provider MUST appear here — list_models ranks by this tuple.
ROUTER_PRIORITY = ("openai", "302ai", "openrouter", "siliconflow",
                   "volcengine", "147ai",
                   # 末位：部分字段仍未实测（计费口径、seed），不该在 auto 路由里
                   # 抢在已验证的 provider 前面。
                   "sensenova")


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


def apply_model_dialect(provider: Provider, model: str) -> Provider:
    """Specialize `provider` for `model` when the gateway fronts several upstream
    protocols on one base_url (see Provider.model_dialects).

    Returns the provider unchanged when no prefix matches, so single-dialect
    providers are entirely unaffected. Call this right after the model is resolved
    and use the result for the rest of the request.
    """
    for prefix, overrides in provider.model_dialects:
        if model.startswith(prefix):
            return dataclasses.replace(provider, **overrides)
    return provider


def endpoint_unset(provider: Provider) -> bool:
    """True when a `requires_base_url` provider has no `{PREFIX}_BASE_URL` set.

    Read from the environment rather than compared against the registry entry, so
    it stays correct for a provider built with `dataclasses.replace` and for a user
    who happens to point the override at the placeholder host. Distinct from "no
    credential": nowhere to send the request disqualifies the provider even under
    `allow_unconfigured` dry-runs.
    """
    if not provider.requires_base_url:
        return False
    return not os.environ.get(f"{_override_prefix(provider)}_BASE_URL", "").strip()


def provider_is_configured(provider: Provider) -> bool:
    """Return whether a provider has both a credential and a usable endpoint."""
    if endpoint_unset(provider):
        return False
    return bool(os.environ.get(provider.key_env, "").strip() and provider.base_url)


def route_provider(*, model: str | None = None, ref_count: int = 0,
                   background: str | None = None, seed: int | None = None,
                   quality: str | None = None,
                   allow_unconfigured: bool = False) -> Provider:
    """Choose the best provider for one CLI request.

    Capability constraints are hard filters. Model and seed support are ranking
    signals because the CLI has historically allowed unknown models and ignored
    unsupported seeds with a warning. Configured providers always beat
    unconfigured ones; `allow_unconfigured` exists for no-network dry-runs.
    """
    candidates: list[tuple[tuple[int, int, int, int], Provider]] = []
    for priority, name in enumerate(ROUTER_PRIORITY):
        provider = resolve_provider(name)
        configured = provider_is_configured(provider)
        if endpoint_unset(provider):
            continue
        if not provider.base_url:
            continue
        if not configured and not allow_unconfigured:
            continue
        if ref_count and (
            provider.edit_path is None
            or provider.edit_style is None
            or ref_count > provider.max_ref_images
        ):
            continue
        effective_model = model or provider.default_model
        if background and effective_model in provider.background_unsupported:
            continue
        # A pinned quality tier is a hard capability, exactly like background: a
        # backend that ignores `quality` would bill for a tier it never applied.
        if quality and quality != "auto":
            if not provider.supports_quality:
                continue
            if (quality in EXTENDED_QUALITY_TIERS
                    and effective_model not in EXTENDED_QUALITY_MODELS):
                continue
        model_match = int(model is None or model in provider.models)
        seed_match = int(seed is None or provider.supports_seed)
        score = (int(configured), model_match, seed_match, -priority)
        candidates.append((score, provider))

    if not candidates:
        detail = []
        if ref_count:
            detail.append(f"{ref_count} reference image(s)")
        if background:
            detail.append(f"background={background}")
        if quality:
            detail.append(f"quality={quality}")
        if model:
            detail.append(f"model={model}")
        suffix = f" for {', '.join(detail)}" if detail else ""
        raise ValueError(
            "no configured image provider satisfies this request"
            f"{suffix}; set one provider's API key (see .env.example) "
            "or choose -p explicitly"
        )
    return max(candidates, key=lambda item: item[0])[1]


def ratio_to_size(provider: Provider, ratio: str) -> str | None:
    """Map an aspect ratio to the provider's size string, or None if the provider
    takes no size parameter (aspect is steered by a prompt hint instead)."""
    if provider.size_style == "openai":
        return OPENAI_RATIO_SIZE.get(ratio, "1024x1024")
    if provider.size_style == "openai_custom":
        return OPENAI_CUSTOM_RATIO_SIZE.get(ratio, "1024x1024")
    if provider.size_style == "sensenova":
        # Fall back to the server's own default member rather than to a value the
        # contract would reject with a 400.
        return SENSENOVA_RATIO_SIZE.get(ratio, "2048x2048")
    if provider.size_style == "wxh":
        return SILICONFLOW_RATIO_SIZE.get(ratio, "1328x1328")
    if provider.size_style == "ark":
        return "2K"
    if provider.size_style == "openai_xl":
        return OPENAI_XL_RATIO_SIZE.get(ratio, "2048x2048")
    if provider.size_style == "image_config":
        # A quality tier, not a WxH — the aspect travels separately in
        # image_config.aspect_ratio, so every ratio maps to the same default tier.
        return DEFAULT_IMAGE_CONFIG_SIZE
    return None
