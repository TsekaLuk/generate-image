---
name: generate-image
description: Use when the user asks to generate, create, draw, or paint an image / illustration / poster / 生图 / 画图 / 出图 / 搞张图, iterates on a design, or provides a reference image (URL or local path) for image-to-image.
---

# generate-image

Generate images through a pluggable **provider registry** — every backend is one
OpenAI-compatible (or near-compatible) entry in `providers.py`. Saves a PNG to
`~/Pictures/generate-image/` and previews inline in kitty.

**Default provider: `openai`** (official OpenAI Images API, model `gpt-image-2`). Switch with
`-p`. Run `./list_models.py` for the live registry.

## Providers (`-p` / `--provider`)

| Provider | 出图端点 | img2img (`--ref`) | size 方言 | Key env |
|---|---|---|---|---|
| **`openai`** (default) | `/v1/images/generations` | ✅ multipart edits | `size`(1024²/1536×1024/1024×1536,真控) | `OPENAI_API_KEY` |
| `302ai` | `/v1/images/generations` | ✅ multipart edits | `size` | `AI302_API_KEY` |
| `openrouter` | `/v1/images` | ✅ chat image_url | 无(靠 `-r` 提示词) | `OPENROUTER_API_KEY` |
| `siliconflow` | `/v1/images/generations` | ✅ image_prompt | `image_size` WxH(真控) | `SILICONFLOW_API_KEY` |

- **Aspect** is set with `-r` (never write ratios into the prompt). On `openai`/
  `302ai` the ratio maps to a real `size` param (1024x1024 / 1536x1024 / 1024x1536);
  on `openrouter` (no size param) the ratio is steered by an auto-injected prompt
  hint; `siliconflow` controls resolution for real via `image_size`.
- **base_url / default model** are env-overridable (`OPENAI_BASE_URL`,
  `OPENROUTER_DEFAULT_MODEL`, …) so a new OpenAI-compatible provider can be
  swapped in without code changes.
- **`--background transparent/opaque/auto`** is passed through where supported
  (the official OpenAI gpt-image models support `background=transparent`) and
  **hard-refused client-side** on any provider/model listed in the registry's
  `background_unsupported`. For matting/抠图 on those, use a chroma-key background
  in the prompt + local key-out instead.

## When to use

- User asks to generate / create / draw an image, illustration, or poster
- User wants to iterate on a design (re-run with tweaked prompt)
- User provides a reference image (URL or local path) for variation / restyle

**Refuse:** content depicting or glamorizing illegal drug use, CSAM, or other
obvious policy violations.

## Reliability (automatic)

Retries, backoff, rate limiting and adaptive concurrency are built in
(`reliability.py`) — you do not manage them by hand:

- **Billing-aware retry:** `302ai` bills success AND failure. 429/408 are always
  retried (rejected before generation); 5xx/timeout are retried only via an
  **idempotency key** (so the gateway dedupes — no double charge). `openai`/
  `openrouter`/`siliconflow` don't bill failures, so their 5xx retry freely.
  Other 4xx never retry.
- **Retry-After** is honored; otherwise full-jitter exponential backoff.
- **Batch** mode adds client-side token-bucket rate limiting + AIMD adaptive
  concurrency (auto-降并发 on 429). Still: each call is real money — confirm the
  prompt count and cost before a batch run.

## Handy flags (DX)

- **`--dry-run`** — print the plan (provider/model/ratio + image count + estimated ¥) and
  exit with **no billed call and no key required**. Use it to honor the cost-preview
  Preflight below before spending; `--dry-run --json` emits a machine-readable plan.
- **`--json`** — emit a machine-readable result to stdout (single: `{ok,path,provider,model,
  ratio,width,height}`; batch/dag: an array); the human banner stays on stderr, and the
  kitty preview is suppressed so stdout is pure JSON.
- Every image also writes a **`<name>.json` metadata sidecar** (prompt/provider/model/ratio/
  refs/dims/timestamp/version) next to the PNG — opt out with `--no-metadata`.
- **`--count N`** — generate N images for a **single** prompt → `<name>_1.png..<name>_N.png`
  (each with its sidecar). `N=1` (default) keeps the plain `<name>.png` / single result.
  `N<1` is rejected up front; not valid with `--batch-file`/`--dag-file`; `--dry-run` reflects
  N in the count and cost. On a mid-sequence failure it aborts but first prints the
  `→ spent:` line for the calls already billed. With `--seed`, siblings use `seed, seed+1, …`
  so a deterministic provider doesn't return N identical images (image 1 keeps the exact seed).
- **`--seed N`** — reproducibility seed, honored only where supported (**siliconflow**);
  on `openai`/`302ai`/`openrouter` it is ignored with a **single** stderr warning per run
  (not once per image/task).
- **`--open`** — after writing, reveal the image(s) in the OS viewer (`open`/`xdg-open`);
  single & `--count` only, best-effort, skipped under `--dry-run` and on failure. With
  `--batch-file`/`--dag-file` it is ignored **with a warning** (not silently).
- **Cost summary** — after every real run a `→ spent: ≈ ¥…（N billed call(s)）` line is printed
  to stderr (`302ai` ≈ ¥0.1/image; other providers show `cost varies`). On a tty a
  live `→ generating… Ns` elapsed indicator shows while a single call runs (stderr only).
- **Env defaults** — `GENIMAGE_PROVIDER` (`-p`), `GENIMAGE_RATIO` (`-r`), `GENIMAGE_OUTPUT_DIR`
  (`-o`) set the defaults; an invalid provider/ratio is ignored with a warning (built-in
  default used), never a hard error. An explicit `-p`/`-r` always wins over the env var and
  suppresses that warning (the env value is only consulted when the flag is omitted).
- **`generate-image-doctor`** — free, no-network diagnostic: lists every provider with its
  base_url, key env, **KEY STATUS (SET/MISSING)** (resolved via the same `.env` loader; the
  value is never printed), img2img support, and default model, ending with
  `N/<total> providers have a key configured`. If the default provider (`openai`) has no
  key it prints a hint pointing at `.env.example`. The default run makes **no
  billed/network call**; add **`--probe`** to do ONE real billed 1:1 generate per keyed
  provider (prints a cost warning first) and report OK/dims or the error. `--probe` exits
  **non-zero if any probe fails** (so `generate-image-doctor --probe && …` is scriptable). Run via
  `uv run generate-image-doctor` — module fallback (no console-script install needed):
  `uv run --no-sync python -m generate_image.doctor [--probe]`.

## Preflight (every call)

Confirm with the user in ONE message before running:

1. **Prompt** — exact text. If vague, ask. Don't invent.
2. **Aspect ratio** — one of `1:1 16:9 9:16 3:2 2:3 4:3 3:4 21:9 4:5 5:4`. Default `16:9`.
3. **Provider + model** — default `-p openai` / `gpt-image-2`. Override only on user
   request. `./list_models.py` shows each provider's models.
4. **Reference image?** — URL or local path (≤10 MB). Omit if none. img2img works
   on all four providers but via different mechanisms (see table).
5. **Transparent background?** — only where the provider/model supports it;
   hard-refused on models the registry marks unsupported.
6. **Batch job?** — `--batch-file prompts.txt` (one prompt per line) + optional
   `--concurrency N` / `--rpm N`. Confirm prompt count and per-image cost first.

## Usage

```bash
# Default provider = openai, gpt-image-2, 16:9
./generate.py "夕阳下的金门大桥，油画风格"
./generate.py -r 9:16 "竖版手机壁纸"                       # aspect via -r

# Switch provider
./generate.py -p siliconflow -m Qwen/Qwen-Image "高清插画"
./generate.py -p openrouter "一只赛博朋克猫"
./generate.py -p 302ai "扁平矢量海报"

# Image-to-image — local file or URL (works on all four, different backends)
./generate.py --ref /tmp/face.png "换成梵高风格"

# Matting where --background is unsupported: chroma-key background + local key-out
./generate.py "一个圆形 App 图标，独立元素。纯色 chroma key 绿色背景 #00FF00，背景无渐变无阴影"

# Batch — one prompt per line
./generate.py --batch-file prompts.txt --concurrency 3
```

Run `./generate.py --help` for every flag. Output path printed to stdout
(pipe-friendly); default filename `img_YYYYMMDD_HHMMSS.png` under
`~/Pictures/generate-image/`.

## DAG orchestration (`--dag-file`)

For dependent / parallel pipelines — B uses A's output, same-style groups,
"A then B/C/D", diamonds, multi-parent joins, or **any acyclic graph** — use a
task-graph spec (YAML or JSON). The engine runs it at maximum parallelism
(stdlib `graphlib.TopologicalSorter`), reusing the reliability layer per provider.

- Each task: `id`, `prompt`, optional `provider` / `model` / `ratio` / `background` / `name`.
- Edges = **union** of `depends_on: [ids]` and any ref `"@id"` (= use that task's
  output image as input → implicit dependency). Multiple `@refs` on one task = a
  **join** compositing several upstream outputs (multi-image).
- `--on-failure skip` (default: a failed task's descendants are skipped, independent
  branches keep running) or `fail-fast` (abort not-yet-started tasks).
- Each task's image → `~/Pictures/generate-image/{name or id}.png`.

```yaml
# pipeline.yaml — A generates; B restyles A; C/D branch off A; E joins C+D
tasks:
  - {id: A, prompt: "a lighthouse at dawn, flat vector", ratio: "16:9"}
  - {id: B, prompt: "same scene at night",   refs: ["@A"]}
  - {id: C, prompt: "close-up of the lamp",  refs: ["@A"]}
  - {id: D, prompt: "wide establishing shot", refs: ["@A"]}
  - {id: E, prompt: "diptych poster",         refs: ["@C", "@D"]}   # multi-parent join
```

```bash
uv run generate-image --dag-file examples/bytedance-logos.yaml --concurrency 3   # runnable example
uv run generate-image --dag-file my-graph.json --on-failure fail-fast            # JSON also works
```

See `examples/bytedance-logos.yaml` for a full runnable spec (10 parallel logos).
`--batch-file` is just the zero-edge special case of a DAG.

## Common mistakes

| Mistake | Fix |
|---|---|
| Writing "长宽比 16:9" in the prompt AND passing `-r 16:9` | Pass `-r` only; the script handles ratio. |
| Expecting 4K from openai/302/openrouter | gpt-image tops out at 1536 on the long edge (`size` capped). Use `siliconflow` with a large `image_size` (via `-r`) for higher resolution. |
| `--ref` expecting identical behavior across providers | openai/302 = OpenAI edits; openrouter = chat; siliconflow = image_prompt remix. Results differ. |
| `--background` on a model the registry marks unsupported | Hard-refused client-side before any billed call. Use the chroma-key workaround. |
| Pasting an API key into chat / commits | Revoke + reissue. Always reference via the `*_API_KEY` env var. |
| Blind-retrying a failed call by hand | Retries are automatic and billing-aware — read the error, don't re-run manually. |
| Reference image > 10 MB | Rejected. Resize first. |
| Putting long text in the image | Models render text poorly; overlay titles in post. |

## Iteration pattern

1. v1 with a draft prompt (cheap provider/model for the first pass).
2. Read the output with `Read`.
3. Name specific defects (wrong element, bad text, missing detail).
4. Propose a revised prompt. Get approval. Generate v2 (escalate provider/model for the keeper).
5. Stop on user accept, or after 3 non-converging iterations (then discuss provider/model fit, not prompt).

## Storybook templates

**Load when:** user asks for a picture book / 绘本 / 故事图 / a set of stylistically
consistent narrative illustrations. Templates live in `templates.md` — read it
only when needed. Every prompt = **1 style preset** + **1 scene scaffold**. For
multi-panel decks, build a fixed **identity lock** paragraph for the protagonist
and pass the previous panel as `--ref` from panel 2 on to reduce character drift.

## Setup (one-time)

uv-native (recommended):

```bash
cd ~/.claude/skills/generate-image
uv sync                               # create .venv, install deps + the package
cp .env.example .env                  # fill in the key(s) for the provider(s) you use
```

Then run with `uv run generate-image "..."` (auto-syncs) or `uv run generate-image-models`.
The top-level `./generate.py` / `./list_models.py` launchers also work (they bootstrap
`src/` onto sys.path) as long as the deps are importable. Non-uv fallback: `pip install .`.

> The usage examples above use `./generate.py` for brevity — `uv run generate-image` is
> the exact equivalent.

`.env` is gitignored. If you accidentally paste a key into chat or a public log,
**revoke it immediately**.

## Layout

```
pyproject.toml · uv.lock          # uv project (deps + console scripts)
generate.py · list_models.py      # thin launchers (→ src/generate_image)
src/generate_image/
  cli.py         — CLI + orchestration (request shaping, response normalization)
  providers.py   — provider registry (dialects + reliability policy)
  reliability.py — pooled httpx client, billing-aware retry, rate limit, AIMD
  dag.py         — task-graph engine (graphlib parallel scheduler) + spec loader
  list_models.py — provider/model listing
  probe.py       — empirically probe ANY provider's real size/aspect behavior
  doctor.py      — free key/config diagnostic (generate-image-doctor; --probe = billed)
examples/ · templates.md · tests/
.env.example                       # credentials template · .env is gitignored
```
