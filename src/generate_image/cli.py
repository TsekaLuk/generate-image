#!/usr/bin/env python3
"""Generate images via a pluggable OpenAI-compatible provider registry.

Default provider: `openai` (official OpenAI Images API). Others: `302ai`,
`openrouter`, `siliconflow`. Reads `{PROVIDER}_API_KEY` from a .env at the project root
(or the process env), saves a PNG to ~/Pictures/generate-image/, and previews
inline with `kitten icat` when running in a kitty terminal.

Provider dialects (endpoint / size param / img2img / response shape) live in
providers.py; the reliability layer (pooled httpx client, billing-aware retry
with Retry-After + idempotency, token-bucket rate limiting, AIMD adaptive
concurrency) lives in reliability.py. This module is the orchestrator: it shapes
requests per dialect, normalizes responses to bytes, and drives the CLI + batch.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx

from . import dag
from . import probe
from . import __version__ as PKG_VERSION
from .providers import (
    PROVIDERS,
    DEFAULT_PROVIDER,
    Provider,
    resolve_provider,
    ratio_to_size,
)
from .reliability import (
    ProviderError,
    build_client,
    is_retryable_status,
    retry_after_seconds,
    call_with_retry,
    new_idempotency_key,
    TokenBucket,
    AdaptiveConcurrency,
)

SCRIPT_DIR = Path(__file__).resolve().parent

VALID_RATIOS = {"1:1", "16:9", "9:16", "3:2", "2:3", "4:3", "3:4", "21:9", "4:5", "5:4"}
DEFAULT_RATIO = "16:9"
# `--size` is a vestigial no-op kept for backward compatibility (no provider uses
# OpenAI's 1K/2K/4K quality tiers; real aspect control is via -r).
VALID_IMAGE_SIZES = {"1K", "2K", "4K"}
OUTPUT_SUBDIR = "generate-image"
MAX_REF_BYTES = 10 * 1024 * 1024

# Aspect steered by prompt wording — used by providers whose size param is absent
# (openrouter) or possibly ignored (some relays). On openai/302ai the `size` param
# controls aspect; the hint is a harmless extra steer there. SiliconFlow ("wxh")
# controls size for real and skips this hint.
RATIO_HINT = {
    "16:9": "画面横向 16:9 宽幅构图 宽明显大于高 landscape",
    "21:9": "画面超宽 21:9 电影宽幅 宽远大于高 ultrawide landscape",
    "3:2":  "画面横向 3:2 宽大于高 landscape",
    "4:3":  "画面横向 4:3 略宽于高 landscape",
    "5:4":  "画面横向 5:4 略宽于高",
    "9:16": "画面竖向 9:16 竖幅构图 高明显大于宽 portrait",
    "2:3":  "画面竖向 2:3 高大于宽 portrait",
    "3:4":  "画面竖向 3:4 略高于宽 portrait",
    "4:5":  "画面竖向 4:5 略高于宽 portrait",
    "1:1":  "",
}

_MIME_BY_EXT = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif",
}

# Test seam: tests inject an httpx.MockTransport here so no real network is hit.
_TEST_TRANSPORT: httpx.BaseTransport | None = None


# --- env / client -------------------------------------------------------------

def _find_dotenv() -> Path | None:
    """Locate a .env by walking up from the CWD (project root), then the packaged
    repo root (…/src/generate_image/cli.py → repo root)."""
    here = Path.cwd().resolve()
    for d in (here, *here.parents):
        p = d / ".env"
        if p.is_file():
            return p
    repo_root = SCRIPT_DIR.parent.parent
    p = repo_root / ".env"
    return p if p.is_file() else None


def _load_dotenv() -> None:
    env_path = _find_dotenv()
    if env_path is None:
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


def require_key(name: str) -> str:
    _load_dotenv()
    key = os.environ.get(name, "").strip()
    if not key:
        sys.exit(
            f"error: {name} not set.\n"
            f"  Add {name}=... to a .env file at the project root (see .env.example),\n"
            f"  or export {name} in your shell."
        )
    return key


def make_client(timeout: int) -> httpx.Client:
    """Pooled httpx client (with the test transport injected when present)."""
    return build_client(transport=_TEST_TRANSPORT, read_timeout=float(timeout))


# --- low-level HTTP (raises classified ProviderError) -------------------------

def _net_retryable(provider: Provider) -> bool:
    """Network/timeout errors are 5xx-like: retry only when safe for billing."""
    return (not provider.bills_on_failure) or provider.supports_idempotency


def _post(client: httpx.Client, url: str, key: str, provider: Provider, *,
          json_body: dict | None = None, files: dict | None = None,
          data: dict | None = None, idem_key: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {key}"}
    if idem_key and provider.supports_idempotency:
        headers["Idempotency-Key"] = idem_key
    try:
        if files is not None:
            resp = client.post(url, headers=headers, files=files, data=data or {})
        else:
            resp = client.post(url, headers=headers, json=json_body)
    except httpx.TimeoutException as e:
        raise ProviderError(f"{provider.name} timeout: {e}", retryable=_net_retryable(provider))
    except httpx.RequestError as e:
        raise ProviderError(f"{provider.name} network error: {e}", retryable=_net_retryable(provider))
    if resp.status_code >= 400:
        retryable = is_retryable_status(
            resp.status_code,
            bills_on_failure=provider.bills_on_failure,
            supports_idempotency=provider.supports_idempotency,
        )
        ra = retry_after_seconds(resp.headers) if resp.status_code in (408, 429) else None
        raise ProviderError(
            f"{provider.name} HTTP {resp.status_code}: {resp.text[:500]}",
            retryable=retryable, retry_after=ra, status=resp.status_code,
        )
    return resp


def _parse_json(resp: httpx.Response, provider: Provider) -> dict:
    try:
        return resp.json()
    except (json.JSONDecodeError, ValueError):
        raise ProviderError(f"{provider.name} non-JSON response: {resp.text[:200]!r}",
                            retryable=False)


def _download(client: httpx.Client, url: str) -> bytes:
    try:
        resp = client.get(url)
    except httpx.RequestError as e:
        raise ProviderError(f"download failed for {url}: {e}", retryable=True)
    if resp.status_code >= 400:
        raise ProviderError(f"download HTTP {resp.status_code} for {url}", retryable=False)
    return resp.content


def _data_url_or_download(client: httpx.Client, url: str) -> bytes:
    if url.startswith("data:"):
        _, _, b64 = url.partition(",")
        return base64.b64decode(b64)
    return _download(client, url)


def _extract_markdown_image(client: httpx.Client, text: str) -> bytes | None:
    """Pull an image out of a chat model's markdown content:
    ![alt](data:image/...;base64,XXX) or ![alt](https://...)."""
    m = re.search(r"!\[[^\]]*\]\((data:image/[^;]+;base64,[A-Za-z0-9+/=]+)\)", text)
    if m:
        return _data_url_or_download(client, m.group(1))
    m = re.search(r"!\[[^\]]*\]\((https?://[^)]+)\)", text)
    if m:
        return _download(client, m.group(1))
    return None


def extract_image_bytes(d: dict, client: httpx.Client, *, provider_name: str = "provider") -> bytes:
    """Normalize any of the provider response shapes to raw image bytes:
    data[].b64_json | data[].url | images[].url | chat choices[].message.images[]/content."""
    data = d.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        item = data[0]
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
        if item.get("url"):
            return _download(client, item["url"])

    images = d.get("images")
    if isinstance(images, list) and images and isinstance(images[0], dict):
        item = images[0]
        if item.get("url"):
            return _download(client, item["url"])
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])

    choices = d.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        for im in msg.get("images") or []:
            url = (im.get("image_url") or {}).get("url") if isinstance(im, dict) else None
            if url:
                return _data_url_or_download(client, url)
        content = msg.get("content")
        if isinstance(content, str):
            b = _extract_markdown_image(client, content)
            if b is not None:
                return b

    if "error" in d:
        raise ProviderError(
            f"{provider_name} api error: {json.dumps(d['error'], ensure_ascii=False)[:300]}",
            retryable=False,
        )
    raise ProviderError(f"{provider_name} returned no image: {json.dumps(d)[:300]}", retryable=False)


# --- request shaping ----------------------------------------------------------

def _shape_prompt(provider: Provider, prompt: str, ratio: str) -> str:
    """Append a ratio hint unless the provider controls size for real (wxh)."""
    if provider.size_style == "wxh":
        return prompt
    hint = RATIO_HINT.get(ratio, "")
    return f"{prompt}。{hint}" if hint else prompt


def _guard_background(provider: Provider, model: str, background: str | None) -> None:
    if background and model in provider.background_unsupported:
        raise ProviderError(
            f"background={background!r} is not supported on {provider.name} model {model!r} "
            f"(omit --background or pick a provider/model that supports it)",
            retryable=False,
        )


def provider_generate(provider: Provider, prompt: str, model: str, ratio: str,
                      key: str, client: httpx.Client, *,
                      background: str | None = None, idem_key: str | None = None,
                      seed: int | None = None) -> bytes:
    """Text-to-image via the provider's generation endpoint."""
    _guard_background(provider, model, background)
    body: dict = {"model": model, "prompt": _shape_prompt(provider, prompt, ratio), "n": 1}
    size = ratio_to_size(provider, ratio)
    if provider.size_style == "openai" and size:
        body["size"] = size
    elif provider.size_style == "wxh" and size:
        body["image_size"] = size
    if background:
        body["background"] = background
    # Seed is only sent where supported; the unsupported-seed warning is emitted
    # ONCE per run by the caller (see _warn_seed_unsupported), not per request, so
    # --count/batch/dag don't spam N identical warnings.
    if seed is not None and provider.supports_seed:
        body["seed"] = seed
    url = provider.base_url + provider.gen_path
    resp = _post(client, url, key, provider, json_body=body, idem_key=idem_key)
    return extract_image_bytes(_parse_json(resp, provider), client, provider_name=provider.name)


def _read_ref(ref: str, client: httpx.Client) -> tuple[bytes, str, str]:
    """Resolve a URL or local path to (bytes, mime, filename), with a 10MB cap."""
    if ref.startswith(("http://", "https://")):
        data = _download(client, ref)
        ext = ref.split("?", 1)[0].rsplit(".", 1)[-1].lower()
        fname = "image." + (ext if ext in ("png", "jpg", "jpeg", "webp") else "png")
    else:
        p = Path(ref).expanduser()
        if not p.is_file():
            sys.exit(f"error: --ref file not found: {ref}")
        data = p.read_bytes()
        ext = p.suffix.lstrip(".").lower()
        fname = p.name
    if len(data) > MAX_REF_BYTES:
        sys.exit(f"error: --ref image exceeds 10MB cap (got {len(data) / 1024 / 1024:.1f}MB)")
    return data, _MIME_BY_EXT.get(ext, "image/png"), fname


def _read_refs(refs: list[str], client: httpx.Client) -> list[tuple[bytes, str, str]]:
    """Resolve every ref to (bytes, mime, filename), preserving input order."""
    return [_read_ref(r, client) for r in refs]


def provider_edit(provider: Provider, prompt: str, model: str, refs: list[str],
                  ratio: str, key: str, client: httpx.Client, *,
                  background: str | None = None, idem_key: str | None = None) -> bytes:
    """Image-to-image (垫图), dispatched by the provider's edit_style."""
    if provider.edit_path is None or provider.edit_style is None:
        raise ProviderError(
            f"{provider.name} does not support image-to-image (--ref); "
            f"use a provider with edit support (openai / 302ai)",
            retryable=False,
        )
    _guard_background(provider, model, background)
    if not refs:
        raise ProviderError(f"{provider.name} edit requires at least one --ref", retryable=False)
    if len(refs) > provider.max_ref_images:
        raise ProviderError(
            f"{provider.name} accepts at most {provider.max_ref_images} reference "
            f"image(s) but {len(refs)} were given. Drop some --ref, or use a provider "
            f"with a higher limit (openai / 302ai support up to 16).",
            retryable=False,
        )
    style = provider.edit_style
    if style == "multipart":
        return _edit_multipart(provider, prompt, model, refs, key, client, background, idem_key)
    if style == "chat_image":
        return _edit_chat_image(provider, prompt, model, refs, key, client, idem_key)
    if style == "image_prompt":
        return _edit_image_prompt(provider, prompt, model, refs, ratio, key, client, idem_key)
    raise ProviderError(f"{provider.name} unknown edit_style {style!r}", retryable=False)


def _edit_multipart(provider, prompt, model, refs, key, client, background, idem_key) -> bytes:
    resolved = _read_refs(refs, client)
    if len(resolved) == 1:
        data, mime, fname = resolved[0]
        files: list | dict = {"image": (fname, data, mime)}
    else:
        # OpenAI gpt-image edits compose multiple inputs via repeated image[] parts.
        files = [("image[]", (fname, data, mime)) for (data, mime, fname) in resolved]
    form = {"model": model, "prompt": prompt, "n": "1"}
    if background:
        form["background"] = background
    url = provider.base_url + provider.edit_path
    resp = _post(client, url, key, provider, files=files, data=form, idem_key=idem_key)
    return extract_image_bytes(_parse_json(resp, provider), client, provider_name=provider.name)


def _edit_chat_image(provider, prompt, model, refs, key, client, idem_key) -> bytes:
    # Text first, then one image_url content part per ref (OpenRouter recommendation).
    content: list = [{"type": "text", "text": prompt}]
    for data, mime, _ in _read_refs(refs, client):
        data_url = f"data:{mime};base64," + base64.b64encode(data).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": data_url}})
    body = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
    }
    url = provider.base_url + provider.edit_path
    resp = _post(client, url, key, provider, json_body=body, idem_key=idem_key)
    return extract_image_bytes(_parse_json(resp, provider), client, provider_name=provider.name)


def _edit_image_prompt(provider, prompt, model, refs, ratio, key, client, idem_key) -> bytes:
    data, mime, _ = _read_ref(refs[0], client)
    b64 = base64.b64encode(data).decode("ascii")
    body = {
        "model": model,
        "prompt": prompt,
        "image_size": ratio_to_size(provider, ratio) or "1328x1328",
        "image_prompt": b64,           # FLUX "image to remix", base64
        "image_prompt_strength": 0.5,
    }
    url = provider.base_url + provider.gen_path
    resp = _post(client, url, key, provider, json_body=body, idem_key=idem_key)
    return extract_image_bytes(_parse_json(resp, provider), client, provider_name=provider.name)


# --- batch mode ----------------------------------------------------------------

def run_batch(jobs: list, call_fn, *, concurrency: int = 3,
              jitter_range: tuple[float, float] = (0.1, 0.3),
              limiter: AdaptiveConcurrency | None = None,
              bucket: TokenBucket | None = None) -> list[dict]:
    """Run `call_fn(job)` for each job with bounded concurrency, order preservation,
    and per-job failure isolation.

    When `limiter` (AdaptiveConcurrency) and/or `bucket` (TokenBucket) are supplied,
    each job first acquires an adaptive slot then a rate-limit token before running
    — giving AIMD backpressure + client-side rate limiting on top of the fixed
    ThreadPoolExecutor cap. Both default to None (legacy behavior).
    """
    results: list[dict | None] = [None] * len(jobs)
    lo, hi = jitter_range

    def _invoke(job):
        if bucket is not None:
            bucket.acquire()
        return call_fn(job)

    def _run_one(index: int, job) -> None:
        try:
            if limiter is not None:
                with limiter.slot():
                    result = _invoke(job)
            else:
                result = _invoke(job)
            results[index] = {"job": job, "result": result, "error": None}
        except Exception as e:  # noqa: BLE001 - failure isolation by design
            results[index] = {"job": job, "result": None, "error": str(e)}

    if jobs:
        if hi > 0 or lo > 0:
            time.sleep(random.uniform(lo, hi))
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as executor:
            futures = [executor.submit(_run_one, i, job) for i, job in enumerate(jobs)]
            for f in futures:
                f.result()

    final_results = [r for r in results if r is not None]
    failure_count = sum(1 for r in final_results if r["error"] is not None)
    if final_results and failure_count / len(final_results) > 0.3:
        print(
            f"→ warning:  batch failure rate {failure_count}/{len(final_results)} "
            f"exceeds 30% — consider 降级 (reducing concurrency) before retrying",
            file=sys.stderr,
        )
    return final_results


# --- shared -------------------------------------------------------------------

def in_kitty() -> bool:
    return "kitty" in os.environ.get("TERM", "") or bool(os.environ.get("KITTY_WINDOW_ID"))


def kitty_preview(path: Path) -> bool:
    if not in_kitty() or not sys.stdout.isatty():
        return False
    kitten = shutil.which("kitten") or shutil.which("kitty")
    if not kitten:
        return False
    cmd = [kitten, "icat", "--align", "left", str(path)] if kitten.endswith("kitten") \
        else [kitten, "+kitten", "icat", "--align", "left", str(path)]
    try:
        subprocess.run(cmd, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# --- metadata sidecar ---------------------------------------------------------

# Single source of truth for per-image ¥ cost. Providers absent from the map bill
# a variable/unknown amount (openrouter / siliconflow depend on the chosen model).
COST_CNY_PER_IMAGE: dict[str, float] = {"302ai": 0.1}


def _billed_cost(counts: dict[str, int]) -> tuple[float | None, int, list[str]]:
    """Reduce a {provider: image_count} tally to
    (known_total_cny_or_None, total_billed_calls, providers_with_varying_cost)."""
    total = 0.0
    billed = 0
    known = False
    varies: list[str] = []
    for name, c in counts.items():
        billed += c
        per = COST_CNY_PER_IMAGE.get(name)
        if per is None:
            if name not in varies:
                varies.append(name)
        else:
            total += per * c
            known = True
    return (round(total, 4) if known else None, billed, varies)


def _cost_phrase(counts: dict[str, int]) -> str:
    """Human cost phrase shared by --dry-run and the post-run summary, e.g.
    '≈ ¥0.30 (3 billed call(s))' or 'cost varies for openrouter (1 billed call(s))'."""
    total, billed, varies = _billed_cost(counts)
    parts: list[str] = []
    if total is not None:
        parts.append(f"≈ ¥{total:.2f}")
    parts.extend(f"cost varies for {name}" for name in varies)
    head = "; ".join(parts) if parts else "cost varies"
    return f"{head} ({billed} billed call(s))"


# --- live progress (single path, tty-only) ------------------------------------

class _progress:
    """Context manager that prints elapsed seconds to STDERR (carriage-return,
    ~once/second) while a blocking call runs — but ONLY when stderr is a tty.

    On a non-tty (pipes, CI, tests) it is a no-op: nothing is ever written and no
    thread is spawned. Never writes to stdout. The worker thread is always joined
    on exit and the status line is cleared."""

    def __init__(self, label: str = "generating", *, interval: float = 1.0) -> None:
        self.label = label
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_progress":
        if sys.stderr.isatty():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def _run(self) -> None:
        t0 = time.time()
        while not self._stop.wait(self.interval):
            secs = int(time.time() - t0)
            sys.stderr.write(f"\r→ {self.label}… {secs}s")
            sys.stderr.flush()

    def __exit__(self, *exc) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            sys.stderr.write("\r" + " " * 40 + "\r")  # clear the status line
            sys.stderr.flush()
        return False


# --- reveal in OS viewer (--open) ---------------------------------------------

def _reveal(paths: list[Path]) -> None:
    """Best-effort reveal of written images in the OS viewer (macOS `open`, else
    `xdg-open`). All errors are swallowed — revealing must never fail a run."""
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    for p in paths:
        try:
            subprocess.run([opener, str(p)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001 - reveal is strictly best-effort
            pass


def _write_metadata(png_path: Path, raw: bytes, *, prompt: str, provider: str,
                    model: str, ratio: str, background: str | None,
                    refs: list[str]) -> None:
    """Write a <name>.json sidecar next to a generated PNG (opt out via --no-metadata).

    Dimensions are decoded from the exact bytes that were written, via
    probe.image_dims (reused, no re-implementation)."""
    w, h, _fmt = probe.image_dims(raw)
    meta = {
        "prompt": prompt,
        "provider": provider,
        "model": model,
        "ratio": ratio,
        "background": background,
        "refs": list(refs or []),
        "width": w,
        "height": h,
        "created": datetime.now().isoformat(),
        "version": PKG_VERSION,
    }
    png_path.with_suffix(".json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# --- cli ----------------------------------------------------------------------

def _env_default_provider() -> str:
    """Default provider from GENIMAGE_PROVIDER, falling back to DEFAULT_PROVIDER.
    An invalid value is IGNORED (built-in default used) with a one-line warning —
    never an argparse hard-error."""
    v = os.environ.get("GENIMAGE_PROVIDER")
    if not v:
        return DEFAULT_PROVIDER
    if v in PROVIDERS:
        return v
    print(f"→ warning: ignoring invalid GENIMAGE_PROVIDER={v!r} "
          f"(using default {DEFAULT_PROVIDER})", file=sys.stderr)
    return DEFAULT_PROVIDER


def _env_default_ratio() -> str:
    """Default ratio from GENIMAGE_RATIO, falling back to DEFAULT_RATIO; an invalid
    value is ignored with a one-line warning."""
    v = os.environ.get("GENIMAGE_RATIO")
    if not v:
        return DEFAULT_RATIO
    if v in VALID_RATIOS:
        return v
    print(f"→ warning: ignoring invalid GENIMAGE_RATIO={v!r} "
          f"(using default {DEFAULT_RATIO})", file=sys.stderr)
    return DEFAULT_RATIO


def _env_default_output_dir() -> str | None:
    """Default output dir from GENIMAGE_OUTPUT_DIR, or None (→ ~/Pictures default)."""
    v = os.environ.get("GENIMAGE_OUTPUT_DIR")
    return v or None


def _warn_seed_unsupported(provider: Provider) -> None:
    """Emit the one-time '--seed ignored' warning for a provider that lacks seed
    support. Callers invoke this ONCE per run (not per image/task)."""
    print(f"→ warning: --seed ignored on {provider.name} (unsupported)", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Generate an image via a pluggable OpenAI-compatible provider "
                    "(openai / 302ai / openrouter / siliconflow).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples (installed console command generate-image; ./generate.py shim also works):\n"
            "  generate-image '夕阳下的金门大桥，油画风格'              # default: openai, 16:9\n"
            "  generate-image -r 9:16 '竖图海报'                       # aspect via prompt hint\n"
            "  generate-image -p siliconflow -m Qwen/Qwen-Image '插画'  # switch provider\n"
            "  generate-image -p openrouter '一只赛博朋克猫'            # openrouter /v1/images\n"
            "  generate-image --ref /tmp/face.png '换成梵高风格'        # img2img (openai/302 native)\n"
            "  generate-image --batch-file prompts.txt --concurrency 3  # batch, one prompt/line\n"
        ),
    )
    ap.add_argument("prompt", nargs="?", help="prompt text (omit to read from stdin)")
    # -p/-r default to None so the GENIMAGE_PROVIDER/GENIMAGE_RATIO env default is
    # resolved (and warned about) AFTER parsing — only when the flag was not given
    # explicitly. This keeps the invalid-env warning off `--help` and off runs where
    # the user overrode the env with -p/-r (the flag always wins).
    ap.add_argument("-p", "--provider", choices=list(PROVIDERS), default=None,
                    help=f"backend provider (default: {DEFAULT_PROVIDER}, or $GENIMAGE_PROVIDER). "
                         f"Run generate-image-models to see each provider's models/keys.")
    ap.add_argument("-m", "--model", default=None,
                    help="model id (default: the provider's default_model). "
                         "Run generate-image-models for options.")
    ap.add_argument("-r", "--ratio", default=None,
                    help=f"aspect ratio (default: {DEFAULT_RATIO}, or $GENIMAGE_RATIO); "
                         f"one of {sorted(VALID_RATIOS)}")
    ap.add_argument("--size", choices=sorted(VALID_IMAGE_SIZES),
                    help="IGNORED (no provider uses OpenAI 1K/2K/4K tiers); kept for "
                         "backward compatibility. Use -r for aspect.")
    ap.add_argument("--ref", action="append",
                    help="reference image URL or local path for img2img (≤10MB each). "
                         "Repeat for multi-image compositing where supported "
                         "(openai/302ai up to 16, openrouter varies, siliconflow 1).")
    ap.add_argument("--background", choices=("auto", "opaque", "transparent"), default=None,
                    help="request a transparent/opaque background where the provider/model "
                         "supports it; hard-refused on models known not to support it.")
    ap.add_argument("-o", "--output-dir", default=_env_default_output_dir(),
                    help=f"output directory (default: ~/Pictures/{OUTPUT_SUBDIR}/, "
                         f"or $GENIMAGE_OUTPUT_DIR)")
    ap.add_argument("-n", "--name",
                    help="output filename stem for single & --batch-file (default: timestamp); "
                         "ignored by --dag-file, whose filenames come from task ids.")
    ap.add_argument("--timeout", type=int, default=300,
                    help="per-request read timeout in seconds (default: 300)")
    ap.add_argument("--seed", type=int, default=None,
                    help="reproducibility seed; only honored where the provider "
                         "supports it (siliconflow). Ignored with a warning on "
                         "providers that don't (openai/302ai/openrouter).")
    ap.add_argument("--count", type=int, default=1,
                    help="how many images to generate for a SINGLE prompt "
                         "(default: 1). N>1 writes <name>_1.png..<name>_N.png; "
                         "not valid with --batch-file/--dag-file.")
    ap.add_argument("--open", action="store_true",
                    help="reveal the written image(s) in the OS viewer afterwards "
                         "(macOS `open`, else `xdg-open`); single/--count only, "
                         "best-effort, skipped under --dry-run and on failure.")
    ap.add_argument("--no-preview", action="store_true",
                    help="skip kitty inline preview even if in kitty (single-image mode only; "
                         "--batch-file/--dag-file never preview).")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan (provider/model/ratio + how many images would be "
                         "generated and the estimated billed cost) and exit; makes NO API "
                         "call and requires NO API key.")
    ap.add_argument("--no-metadata", action="store_true",
                    help="do not write a <name>.json metadata sidecar next to each image "
                         "(sidecars are written by default).")
    ap.add_argument("--json", action="store_true",
                    help="print a machine-readable JSON result to stdout (single: an object; "
                         "batch/dag: an array) and suppress the plain output-path line; the "
                         "human banner stays on stderr.")
    ap.add_argument("--batch-file",
                    help="text file with one prompt per line (blank lines and lines "
                         "starting with # are skipped). Makes the positional prompt optional. "
                         "Exits 0 when at least one job succeeds (partial failures are "
                         "non-fatal), unlike --dag-file which exits nonzero on any partial "
                         "failure.")
    ap.add_argument("--concurrency", type=int, default=None,
                    help="max concurrent jobs; applies to both --batch-file "
                         "(default: provider's default_concurrency) and --dag-file "
                         "(default: 4).")
    ap.add_argument("--rpm", type=int, default=None,
                    help="client-side rate limit (requests/minute); --batch-file only "
                         "(default: provider's rpm). Ignored by --dag-file, which uses each "
                         "provider's rpm.")
    ap.add_argument("--dag-file",
                    help="YAML/JSON task-graph spec for dependent + parallel generation. "
                         "Each task: id/prompt/provider/model/ratio/refs/depends_on; a ref "
                         "'@id' uses that task's output image (implicit dependency). Any "
                         "acyclic graph. Makes the positional prompt optional. Exits nonzero "
                         "on any task failure/skip (partial completion), unlike --batch-file.")
    ap.add_argument("--on-failure", choices=list(dag.ON_FAILURE_CHOICES), default=dag.ON_FAILURE_SKIP,
                    help="--dag-file failure policy: 'skip' (skip a failed task's "
                         "descendants, keep independent branches) or 'fail-fast' (abort "
                         "not-yet-started tasks). Default: skip.")
    return ap.parse_args()


def _read_batch_prompts(batch_file: str) -> list[str]:
    path = Path(batch_file).expanduser()
    if not path.is_file():
        sys.exit(f"error: --batch-file not found: {batch_file}")
    prompts = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        prompts.append(stripped)
    return prompts


def _dry_run_plan(args) -> None:
    """--dry-run: print the plan to stderr and exit 0, with NO key and NO network.

    Short-circuits BEFORE require_key() and any httpx client on all three paths.
    Image count: 1 (single), usable-prompt count (--batch-file), task count (--dag-file).
    """
    if args.dag_file:
        try:
            tasks = dag.load_dag(args.dag_file)
        except dag.DagError as e:
            sys.exit(f"error: {e}")
        print("→ dry-run: no API call, no key required", file=sys.stderr)
        print(f"→ dag-file: {args.dag_file} ({len(tasks)} task(s))", file=sys.stderr)
        json_tasks: list[dict] = []
        for t in tasks:
            prov = t.provider or DEFAULT_PROVIDER
            model = t.model or "(provider default)"
            ratio = t.ratio or DEFAULT_RATIO
            print(f"→   {t.id}: provider={prov} model={model} ratio={ratio}", file=sys.stderr)
            resolved_model = t.model or (
                resolve_provider(prov).default_model if prov in PROVIDERS else None)
            json_tasks.append({"id": t.id, "provider": prov, "model": resolved_model,
                               "ratio": ratio})
        counts = Counter(t.provider or DEFAULT_PROVIDER for t in tasks)
        print(f"→ images:   {len(tasks)}", file=sys.stderr)
        print(f"→ cost:     {_cost_phrase(counts)}", file=sys.stderr)
        if args.json:
            print(json.dumps({
                "mode": "dag", "images": len(tasks),
                "estimated_cost_cny": _billed_cost(counts)[0], "tasks": json_tasks,
            }, ensure_ascii=False))
        return

    provider = resolve_provider(args.provider)
    model = args.model or provider.default_model
    if args.batch_file:
        prompts = _read_batch_prompts(args.batch_file)
        if not prompts:
            sys.exit(f"error: --batch-file {args.batch_file!r} has no usable prompts "
                     f"(all lines blank or comments)")
        n = len(prompts)
    else:
        n = max(1, args.count)  # --count images of a single prompt
    counts = {provider.name: n}
    print("→ dry-run: no API call, no key required", file=sys.stderr)
    print(f"→ provider: {provider.name}", file=sys.stderr)
    print(f"→ model:    {model}", file=sys.stderr)
    print(f"→ ratio:    {args.ratio}", file=sys.stderr)
    print(f"→ images:   {n}", file=sys.stderr)
    print(f"→ cost:     {_cost_phrase(counts)}", file=sys.stderr)
    if args.json:
        print(json.dumps({
            "mode": "batch" if args.batch_file else "single",
            "provider": provider.name, "model": model, "ratio": args.ratio,
            "images": n, "estimated_cost_cny": _billed_cost(counts)[0],
        }, ensure_ascii=False))


def _run_batch_file(args, provider: Provider, model: str, key: str,
                    out_dir: Path, stem: str) -> None:
    prompts = _read_batch_prompts(args.batch_file)
    if not prompts:
        sys.exit(f"error: --batch-file {args.batch_file!r} has no usable prompts "
                 f"(all lines blank or comments)")

    if args.seed is not None and not provider.supports_seed:
        _warn_seed_unsupported(provider)  # once for the whole batch

    concurrency = args.concurrency or provider.default_concurrency
    rpm = args.rpm or provider.rpm
    client = make_client(args.timeout)
    bucket = TokenBucket(rpm)
    limiter = AdaptiveConcurrency(concurrency, concurrency)
    jobs = [{"index": i, "prompt": p} for i, p in enumerate(prompts, start=1)]

    def _throttle_cb(retry_state) -> None:
        exc = retry_state.outcome.exception()
        if isinstance(exc, ProviderError) and exc.status == 429:
            limiter.on_throttle()

    def call_fn(job: dict) -> bytes:
        idem = new_idempotency_key()
        raw = call_with_retry(
            lambda: provider_generate(provider, job["prompt"], model, args.ratio,
                                      key, client, background=args.background,
                                      idem_key=idem, seed=args.seed),
            max_attempts=provider.max_retries,
            before_sleep=_throttle_cb,
        )
        limiter.on_success()
        return raw

    try:
        results = run_batch(jobs, call_fn, concurrency=concurrency,
                            limiter=limiter, bucket=bucket)
    finally:
        client.close()

    json_items: list[dict] = []
    succeeded = 0
    for r in results:
        job = r["job"]
        if r["error"] is not None:
            print(f"→ warning:  batch job {job['index']} failed: {r['error']}", file=sys.stderr)
            json_items.append({"index": job["index"], "ok": False, "path": None,
                               "error": r["error"]})
            continue
        png = out_dir / f"{stem}_{job['index']:03d}.png"
        png.write_bytes(r["result"])
        if not args.no_metadata:
            _write_metadata(png, r["result"], prompt=job["prompt"], provider=provider.name,
                            model=model, ratio=args.ratio, background=args.background, refs=[])
        json_items.append({"index": job["index"], "ok": True, "path": str(png), "error": None})
        succeeded += 1

    total = len(results)
    print(f"batch: {succeeded}/{total} succeeded", file=sys.stderr)
    # Some providers (302ai) bill success AND failure, so every attempted job
    # counts toward the cost summary.
    print(f"→ spent: {_cost_phrase({provider.name: total})}", file=sys.stderr)
    if args.json:
        print(json.dumps(json_items, ensure_ascii=False))
    if succeeded == 0:
        sys.exit(f"error: all {total} batch jobs failed")


def _run_dag_file(args, out_dir: Path) -> None:
    """Run a task-graph spec (--dag-file): build per-provider reliability, execute
    the DAG at max parallelism, and report a per-task summary."""
    try:
        tasks = dag.load_dag(args.dag_file)
    except dag.DagError as e:
        sys.exit(f"error: {e}")

    # Validate per-task provider/ratio up front (fail before any billed request).
    for t in tasks:
        if t.provider and t.provider not in PROVIDERS:
            sys.exit(f"error: task {t.id!r} unknown provider {t.provider!r}; "
                     f"choices: {list(PROVIDERS)}")
        if t.ratio and t.ratio not in VALID_RATIOS:
            sys.exit(f"error: task {t.id!r} invalid ratio {t.ratio!r}; "
                     f"choose from {sorted(VALID_RATIOS)}")

    # Warn ONCE per distinct provider that ignores --seed (outside the worker
    # threads), instead of once per task.
    if args.seed is not None:
        warned: set[str] = set()
        for t in tasks:
            prov = resolve_provider(t.provider or DEFAULT_PROVIDER)
            if not prov.supports_seed and prov.name not in warned:
                warned.add(prov.name)
                _warn_seed_unsupported(prov)

    concurrency = args.concurrency or 4
    client = make_client(args.timeout)
    buckets: dict[str, TokenBucket] = {}
    limiters: dict[str, AdaptiveConcurrency] = {}
    keys: dict[str, str] = {}

    def execute(task: dag.Task, refs: list[str]) -> bytes:
        provider = resolve_provider(task.provider or DEFAULT_PROVIDER)
        model = task.model or provider.default_model
        ratio = task.ratio or DEFAULT_RATIO
        if provider.key_env not in keys:
            keys[provider.key_env] = require_key(provider.key_env)
        key = keys[provider.key_env]
        # per-provider rate limit + AIMD limiter, shared across all tasks of that provider
        bucket = buckets.setdefault(provider.name, TokenBucket(provider.rpm))
        limiter = limiters.setdefault(provider.name, AdaptiveConcurrency(concurrency, concurrency))
        idem = new_idempotency_key()

        def _throttle(retry_state) -> None:
            exc = retry_state.outcome.exception()
            if isinstance(exc, ProviderError) and exc.status == 429:
                limiter.on_throttle()

        def attempt() -> bytes:
            if refs:
                return provider_edit(provider, task.prompt, model, refs, ratio, key,
                                     client, background=task.background, idem_key=idem)
            return provider_generate(provider, task.prompt, model, ratio, key, client,
                                     background=task.background, idem_key=idem, seed=args.seed)

        with limiter.slot():
            bucket.acquire()
            raw = call_with_retry(attempt, max_attempts=provider.max_retries,
                                  before_sleep=_throttle)
        limiter.on_success()
        return raw

    try:
        results = dag.run_dag(tasks, execute, out_dir=out_dir,
                              concurrency=concurrency, on_failure=args.on_failure)
    except dag.DagError as e:
        sys.exit(f"error: {e}")
    finally:
        client.close()

    json_items: list[dict] = []
    n_ok = n_fail = n_skip = 0
    for t in tasks:
        r = results[t.id]
        line = f"→ {t.id}: {r.status}"
        if r.output_path:
            line += f" -> {r.output_path}"
        if r.error:
            line += f"  ({r.error})"
        print(line, file=sys.stderr)
        n_ok += r.status == dag.SUCCESS
        n_fail += r.status == dag.FAILED
        n_skip += r.status == dag.SKIPPED
        # sidecars are written here (from run_dag's results + the task specs) so
        # dag.py stays generic and free of image-gen knowledge.
        if not args.no_metadata and r.status == dag.SUCCESS and r.output_path:
            png = Path(r.output_path)
            try:
                raw = png.read_bytes()
            except OSError:
                raw = b""
            if raw:
                prov_name = t.provider or DEFAULT_PROVIDER
                model = t.model or resolve_provider(prov_name).default_model
                _write_metadata(png, raw, prompt=t.prompt, provider=prov_name, model=model,
                                ratio=t.ratio or DEFAULT_RATIO, background=t.background,
                                refs=list(t.refs))
        json_items.append({"id": t.id, "ok": r.status == dag.SUCCESS,
                           "path": r.output_path, "error": r.error})
    print(f"dag: {n_ok} ok, {n_fail} failed, {n_skip} skipped ({len(tasks)} total)",
          file=sys.stderr)
    # Only tasks that actually ran (succeeded or failed) issue a billed call;
    # skipped descendants never reach the network.
    billed_counts = Counter(
        t.provider or DEFAULT_PROVIDER
        for t in tasks if results[t.id].status in (dag.SUCCESS, dag.FAILED)
    )
    if billed_counts:
        print(f"→ spent: {_cost_phrase(billed_counts)}", file=sys.stderr)
    if args.json:
        print(json.dumps(json_items, ensure_ascii=False))
    if n_ok == 0:
        sys.exit("error: no dag task produced an image")
    if n_fail or n_skip:
        sys.exit(1)  # partial completion -> nonzero exit


def main() -> None:
    args = parse_args()

    # Resolve env-var defaults AFTER parsing, and only when the flag was not given
    # explicitly — so an explicit -p/-r always beats GENIMAGE_PROVIDER/GENIMAGE_RATIO
    # and an invalid env value only warns when it's actually the effective value.
    if args.provider is None:
        args.provider = _env_default_provider()
    if args.ratio is None:
        args.ratio = _env_default_ratio()

    if args.count < 1:
        sys.exit("error: --count must be >= 1")

    if args.count != 1 and (args.batch_file or args.dag_file):
        sys.exit("error: --count applies to single-prompt mode only "
                 "(not with --batch-file/--dag-file)")

    if args.open and (args.batch_file or args.dag_file):
        print("→ warning: --open ignored with --batch-file/--dag-file "
              "(single/--count only)", file=sys.stderr)

    if args.batch_file or args.dag_file:
        prompt = args.prompt or ""
    else:
        prompt = args.prompt if args.prompt else sys.stdin.read().strip()
        if not prompt:
            sys.exit("error: empty prompt (pass as arg or pipe via stdin)")

    if args.dry_run:
        _dry_run_plan(args)
        return

    out_dir = Path(args.output_dir).expanduser() if args.output_dir \
        else Path.home() / "Pictures" / OUTPUT_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.dag_file:
        _run_dag_file(args, out_dir)
        return

    if args.ratio not in VALID_RATIOS:
        sys.exit(f"error: invalid ratio {args.ratio!r}; choose from {sorted(VALID_RATIOS)}")

    provider = resolve_provider(args.provider)
    model = args.model or provider.default_model

    stem = args.name or f"img_{datetime.now():%Y%m%d_%H%M%S}"

    if args.size:
        print(f"→ warning:  --size {args.size} ignored (use -r for aspect)", file=sys.stderr)

    print(f"→ provider: {provider.name}", file=sys.stderr)

    if args.batch_file:
        key = require_key(provider.key_env)
        _run_batch_file(args, provider, model, key, out_dir, stem)
        return

    if model not in provider.models:
        print(f"→ warning:  {model!r} not in {provider.name}'s known models "
              f"{sorted(provider.models)} — sending anyway", file=sys.stderr)
    print(f"→ model:    {model}", file=sys.stderr)
    print(f"→ ratio:    {args.ratio}", file=sys.stderr)
    if args.background:
        print(f"→ background: {args.background}", file=sys.stderr)
    for r in args.ref or []:
        ok = r.startswith(("http://", "https://")) or Path(r).expanduser().is_file()
        if not ok:
            sys.exit(f"error: --ref file not found: {r}")
        print(f"→ ref:      {r}  (image-to-image)", file=sys.stderr)
    preview = prompt[:120] + ("…" if len(prompt) > 120 else "")
    print(f"→ prompt:   {preview}", file=sys.stderr)
    count = max(1, args.count)
    if count > 1:
        print(f"→ count:    {count}", file=sys.stderr)
    if args.seed is not None and not provider.supports_seed:
        _warn_seed_unsupported(provider)  # once per run, before the loop

    key = require_key(provider.key_env)
    client = make_client(args.timeout)
    clean_stem = stem.removesuffix(".png")

    def _attempt(img_seed: int | None) -> bytes:
        # a fresh idempotency key per image so retries dedupe but siblings don't
        idem = new_idempotency_key()
        if args.ref:
            return provider_edit(provider, prompt, model, args.ref, args.ratio, key,
                                 client, background=args.background, idem_key=idem)
        return provider_generate(provider, prompt, model, args.ratio, key, client,
                                 background=args.background, idem_key=idem, seed=img_seed)

    json_items: list[dict] = []
    written: list[Path] = []
    try:
        for i in range(1, count + 1):
            target = out_dir / (f"{clean_stem}.png" if count == 1
                                else f"{clean_stem}_{i}.png")
            # Offset the seed per sibling so a deterministic provider (siliconflow)
            # doesn't return N identical images; i=1 keeps the exact given seed.
            img_seed = None if args.seed is None else args.seed + (i - 1)
            t0 = time.time()
            try:
                with _progress("generating"):
                    raw = call_with_retry(lambda s=img_seed: _attempt(s),
                                          max_attempts=provider.max_retries)
            except ProviderError as e:
                # Surface cost already billed before aborting (providers with
                # bills_on_failure bill the failed call too; successful siblings
                # were billed regardless).
                billed = len(written) + (1 if provider.bills_on_failure else 0)
                if billed:
                    print(f"→ spent: {_cost_phrase({provider.name: billed})}",
                          file=sys.stderr)
                if args.json:
                    if count == 1:
                        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
                    else:
                        json_items.append({"ok": False, "path": None, "error": str(e)})
                        print(json.dumps(json_items, ensure_ascii=False))
                    sys.exit(1)
                sys.exit(f"error: {e}")
            target.write_bytes(raw)
            if not args.no_metadata:
                _write_metadata(target, raw, prompt=prompt, provider=provider.name,
                                model=model, ratio=args.ratio, background=args.background,
                                refs=args.ref or [])
            w, h, _fmt = probe.image_dims(raw)
            json_items.append({"ok": True, "path": str(target), "error": None,
                               "width": w, "height": h})
            written.append(target)
            print(f"✓ generated in {time.time() - t0:.1f}s, saved to {target}", file=sys.stderr)
    finally:
        client.close()

    # cost summary for the real run (302ai bills each call; others vary)
    print(f"→ spent: {_cost_phrase({provider.name: count})}", file=sys.stderr)

    if args.json:
        if count == 1:
            r = json_items[0]
            print(json.dumps({
                "ok": True, "path": r["path"], "error": None, "provider": provider.name,
                "model": model, "ratio": args.ratio, "width": r["width"], "height": r["height"],
            }, ensure_ascii=False))
        else:
            print(json.dumps(json_items, ensure_ascii=False))
    else:
        for p in written:
            print(p)

    # kitty inline preview: single-image, non-json only (unchanged behavior)
    if count == 1 and not args.no_preview and not args.json:
        kitty_preview(written[0])
    if args.open:
        _reveal(written)


if __name__ == "__main__":
    main()
