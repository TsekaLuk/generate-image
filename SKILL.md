---
name: generate-image
description: Use when the user asks to generate, create, draw, or paint an image / illustration / poster / 生图 / 画图 / 出图 / 搞张图, iterates on a design, provides a reference image for image-to-image, or needs a coherent multi-image family with controlled variations and identity consistency.
---

# generate-image

Generate images through a pluggable **provider registry** — every backend is one
OpenAI-compatible (or near-compatible) entry in `providers.py`. Saves a PNG to
`~/Pictures/generate-image/` and previews inline in kitty.

**Default: `auto` capability routing.** The router selects the first configured
provider that satisfies the request's model, img2img, background, and seed
requirements. Use `-p` to force a provider. Run
`./list_models.py` for the live registry.

## Providers (`-p` / `--provider`)

| Provider | 出图端点 | img2img (`--ref`) | size 方言 | Key env |
|---|---|---|---|---|
| **`openai`** (auto first) | `/v1/images/generations` | ✅ multipart edits | `size`(1024²/1536×1024/1024×1536,真控) | `OPENAI_API_KEY` |
| `302ai` | `/v1/images/generations` | ✅ multipart edits | `size` | `AI302_API_KEY` |
| `openrouter` | `/v1/images` | ✅ chat image_url | 无(靠 `-r` 提示词) | `OPENROUTER_API_KEY` |
| `siliconflow` | `/v1/images/generations` | ✅ image_prompt | `image_size` WxH(真控) | `SILICONFLOW_API_KEY` |
| `volcengine` | `/api/v3/images/generations` | ✅ Ark JSON `image[]` (local refs → Base64) | `size: 2K` + `-r` hint | `ARK_API_KEY` |
| `147ai` | 双方言,随模型自动切换(见下) | ✅ 两条线都支持 | **真控**,可到 4K | `AI147_API_KEY` |

### `147ai`(nn.147ai.com,站名 Nano Banana)

**一个 base_url 前面挂了两套上游协议**,`-m` 选的模型决定走哪条 —— 你不用管,
`apply_model_dialect()` 自动切:

| 模型前缀 | 端点 | 画幅控制 | img2img |
|---|---|---|---|
| `gemini-*`(默认) | `/v1/chat/completions` | `extra_body.google.image_config.{aspect_ratio, image_size}`,tier = `1K`/`2K`/`4K` | 同端点,图作 `image_url` 部件,**且能定画幅** |
| `gpt-image-2-*` | `/v1/images/generations` | `size` 枚举真生效 | `/v1/images/edits` multipart |

**实测分辨率(2026-07,`generate-image-probe` 同法测得,非文档抄写):**

| 模型 | tier | 16:9 | 1:1 | 21:9 |
|---|---|---|---|---|
| `gemini-3-pro-image-preview` | `4K` | 5504x3072(16.9MP) | 4096x4096(16.8MP) | 6336x2688(17.0MP) |
| `gemini-3-pro-image-preview` | `1K` | 1376x768(1.06MP) | — | — |
| `gemini-2.5-flash-image` | 1K/2K/**4K 均无效** | 1344x768(1.03MP) | — | — |
| `gpt-image-2-low` | (无 tier) | 2048x1152(2.4MP) | 2048x2048(4.2MP) | — |

- **`image_size` 只在 pro 模型上生效**。`gemini-2.5-flash-image` 三档返回完全相同的
  1344x768 —— 想要高分辨率必须用 `gemini-3-pro-image-preview` + `GENIMAGE_IMAGE_SIZE=4K`,
  那是 **16.9MP,官方 `size` 上限(1.57MP)的 10.8 倍**,本 skill 分辨率天花板。
- 画幅 `-r` 在两条线上都精确生效(21:9 实测比例 2.36)。
- 画质档由**模型名**决定,不是 `quality` 参数:`gpt-image-2-low/-medium/-high`。
- 单价按模型差 10 倍,`--dry-run` 会报准确 ¥ 数(表在 `cli.COST_CNY_PER_IMAGE_BY_MODEL`,
  源头是该站免 key 的 `/api/pricing`,价格会漂,对不上就重查那个接口)。
- `n>1` 文档明说"收到但仍只出一张",所以多图一律走 `--count`(N 次独立调用)。
- 无 `seed`、无 `background` 参数(文档未提供)。

**⚠️ 背靠背请求会被切断连接**(实测必现):连续调用报
`[SSL: UNEXPECTED_EOF_WHILE_READING]`,冷却约 20 秒后恢复。而且**这种失败照样计费**,
所以本 provider 特意设成"断连要重试"(`retry_broken_transport`)+ 20 秒退避下限 +
并发 1 + rpm 12 —— 不重试并不省钱,只是白付。gpt-image-2 线单次耗时 50~140 秒,
批量任务请预留时间。

`volcengine` models: default `doubao-seedream-5-0-260128`, lite
`doubao-seedream-5-0-lite-260128`, and Pro
`doubao-seedream-5-0-pro-260628`. Pro must be activated for the account that owns
`ARK_API_KEY`; its current ≤2.36 MP tier is ¥0.3/output image, with the first input
image free and each additional input image ¥0.02. Recheck the Ark console before a
large run because pricing and activation are account-specific.

- **Aspect** is set with `-r` (never write ratios into the prompt). On `openai` the
  `size` param is honored for real; `302ai`/`openrouter`/`volcengine` steer the ratio
  through an auto-injected prompt hint instead (a relay fronting gpt-image may ignore
  `size` entirely, so the hint keeps aspect control working there). `siliconflow`
  (`image_size`) and `147ai` (`aspect_ratio` / a honored `size` enum) control
  resolution for real, and get **no** prompt hint injected because they don't need one.
- **base_url / default model** are env-overridable (`OPENAI_BASE_URL`,
  `OPENROUTER_DEFAULT_MODEL`, …) so a new OpenAI-compatible provider can be
  swapped in without code changes.
- **`--background transparent/opaque/auto`** is passed through where supported
  (official gpt-image models do) and **hard-refused client-side** on models known
  not to (the whole Seedream line). For matting/抠图 on those, use a chroma-key
  background in the prompt + local key-out instead.

## When to use

- User asks to generate / create / draw an image, illustration, or poster
- User wants to iterate on a design (re-run with tweaked prompt)
- User provides a reference image (URL or local path) for variation / restyle

**Refuse:** content depicting or glamorizing illegal drug use, CSAM, or other
obvious policy violations.

## Reliability (automatic)

Retries, backoff, rate limiting and adaptive concurrency are built in
(`reliability.py`) — you do not manage them by hand:

- **Billing-aware retry:** `302ai` and Ark bill success AND failure. 429/408 are
  always retried (rejected before generation); 5xx/timeout are retried only via an
  **idempotency key** (so the gateway dedupes — no double charge). `openrouter`/
  `siliconflow` don't bill failures, so their 5xx retry freely. Ark does not document
  idempotency, so `volcengine` conservatively does not retry ambiguous 5xx/timeouts.
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
- **`--seed N`** — reproducibility seed, honored by **siliconflow** and
  **volcengine**; on `openai`/`302ai`/`openrouter` it is ignored with a **single** stderr warning per run
  (not once per image/task).
- **`--sequential --max-images N`** — `volcengine`/Seedream only: request a coherent
  image sequence in one Ark call and save every returned `data[]` item as
  `<name>_1.png..<name>_N.png`. `N` must be 1..15. This is distinct from `--count`,
  which makes independent calls. Seedream 5.0 Pro does not support Ark's
  `sequential_image_generation` field; use the default 5.0 model for this mode.
- **`--open`** — after writing, reveal the image(s) in the OS viewer (`open`/`xdg-open`);
  single & `--count` only, best-effort, skipped under `--dry-run` and on failure. With
  `--batch-file`/`--dag-file` it is ignored **with a warning** (not silently).
- **Cost summary** — after every real run a `→ spent: ≈ ¥…（N billed call(s)）` line is printed
  to stderr (`302ai` ≈ ¥0.1/image; other providers show `cost varies`). On a tty a
  live `→ generating… Ns` elapsed indicator shows while a single call runs (stderr only).
- **Env defaults** — `GENIMAGE_PROVIDER` (`-p`, default `auto`), `GENIMAGE_RATIO` (`-r`), `GENIMAGE_OUTPUT_DIR`
  (`-o`) set the defaults; an invalid provider/ratio is ignored with a warning (built-in
  default used), never a hard error. An explicit `-p`/`-r` always wins over the env var and
  suppresses that warning (the env value is only consulted when the flag is omitted).
- **`generate-image-doctor`** — free, no-network diagnostic: lists every provider with its
  base_url, key env, **KEY STATUS (SET/MISSING)** (resolved via the same `.env` loader; the
  value is never printed), img2img support, and default model, ending with
  `N/<total> providers have a key configured` and the provider currently selected
  by auto routing. If the default provider (`openai`) has no key it prints a
  hint pointing at `.env.example`. The default run makes **no
  billed/network call**; add **`--probe`** to do ONE real billed 1:1 generate per keyed
  provider (prints a cost warning first) and report OK/dims or the error. `--probe` exits
  **non-zero if any probe fails** (so `generate-image-doctor --probe && …` is scriptable). Run via
  `uv run generate-image-doctor` — module fallback (no console-script install needed):
  `uv run --no-sync python -m generate_image.doctor [--probe]`.

## Preflight (every call)

Confirm with the user in ONE message before running:

1. **Prompt** — exact text. If vague, ask. Don't invent.
2. **Aspect ratio** — one of `1:1 16:9 9:16 3:2 2:3 4:3 3:4 21:9 4:5 5:4`. Default `16:9`.
3. **Provider + model** — default `-p auto`; report the routed provider/model in
   the cost preview. Override only on user request. `./list_models.py` shows each
   provider's models.
4. **Reference image?** — URL or local path (≤10 MB). Omit if none. img2img works
   on all five providers but via different mechanisms (see table).
5. **Transparent background?** — only where the provider/model supports it;
   hard-refused on the Seedream line.
6. **Batch job?** — `--batch-file prompts.txt` or `--dag-file tasks.yaml` + optional
   concurrency controls. Confirm the exact task count and provider cost first.

## Usage

```bash
# Default = auto route, 16:9
./generate.py "夕阳下的金门大桥，油画风格"
./generate.py -r 9:16 "竖版手机壁纸"                       # aspect via -r

# Switch provider
./generate.py -p openai "品牌标志"
./generate.py -p siliconflow -m Qwen/Qwen-Image "高清插画"
./generate.py -p openrouter "一只赛博朋克猫"
./generate.py -p 302ai "扁平矢量海报"
./generate.py -p volcengine "中文信息图"
./generate.py -p volcengine -m doubao-seedream-5-0-pro-260628 "商业海报"

# 147ai — dialect follows the model, nothing else to configure
./generate.py -p 147ai "一只赛博朋克猫"                      # gemini-3-pro, 2K
GENIMAGE_IMAGE_SIZE=4K ./generate.py -p 147ai -r 21:9 "超宽壁纸"   # 实测 6336x2688
./generate.py -p 147ai -m gpt-image-2-high -r 1:1 "产品图"    # 2048², OpenAI dialect
./generate.py -p 147ai -m gemini-2.5-flash-image "草稿"       # ¥0.04,但恒定 ~1MP

# Image-to-image — local file or URL (works on all five, different backends)
./generate.py --ref /tmp/face.png "换成梵高风格"

# Seedream coherent multi-image output in one request
./generate.py -p volcengine --sequential --max-images 4 "四格连贯分镜"

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

## Bounded control flows (`--flow-file`)

Use Flow when generation has acceptance criteria and may need feedback-driven
prompt revision. Unlike the parallel data DAG, Flow follows one named route per
node and permits cycles. Every cyclic spec must declare `limits.max_steps`; also
set `max_billed_calls` so an evaluator can never spend without a hard ceiling.

```bash
uv run generate-image --flow-file examples/acceptance-loop.yaml --dry-run
uv run generate-image --flow-file examples/acceptance-loop.yaml -n keyboard-loop
```

Built-in nodes are `image.describe`, `image.generate`, `image.review`, and
`prompt.refine`. `image.describe` derives the initial prompt from a target image;
`image.review` can receive both `reference` and candidate `image` for comparison. The
review service uses the registered `openai` or `openrouter` provider's
OpenAI-compatible multimodal chat and returns structured
`accepted` / `score` / `feedback` / `revised_prompt`. Outputs are immutable under
`runs/<run-name>/<node>/attempt-NNN/`, with `journal.jsonl` and `state.json` at the
run root. See `examples/acceptance-loop.yaml` for the complete spec.

## Coherent series generation

Use this workflow for any multi-image family that must keep a subject, product,
character, place, visual language, or composition system recognizable while
varying views, states, actions, seasons, colors, styling, or context.

### Define the consistency contract

1. Select one approved canonical reference. Copy it to a stable path before a
   long batch; do not depend on a temporary clipboard path.
2. State each reference's role explicitly: identity/geometry, material/style,
   composition, or palette. Also state what it must not contribute.
3. Split every prompt into the same four blocks:
   - **Invariant contract:** geometry/topology, proportions, part count,
     identifying marks, material, and other features that must not drift.
   - **Declared variation:** the one primary change assigned to this node.
   - **Scene/render contract:** camera, lighting, background, crop, padding,
     and output intent that should remain comparable across siblings.
   - **Targeted negatives:** likely failure modes, not a generic adjective dump.
4. Repeat the invariant, scene, and negative blocks verbatim across siblings.
   Change only the declared variation unless a combination is intentional and
   explicitly enumerated.

For independent siblings, pass the same canonical image as `--ref` to every
node. Avoid chaining sibling A -> B -> C: serial references accumulate drift.
Use a previous output as the next reference only when temporal or narrative
continuity is more important than exact return to the canonical identity.

### Build a controlled matrix

- Divide a large request into named dimensions, then assign stable IDs,
  filenames, and one deliverable per node. Make combinations deliberate rather
  than producing random permutations.
- Preserve semantic roles when changing color or material: map light, mid,
  dark, accent, seam, and face values consistently instead of recoloring every
  region independently.
- Count functional parts after posing. A limb used as an arm, handle, branch,
  flap, or gesture still counts toward the declared total.
- Keep props, clothing, effects, and scenery subordinate to the invariant
  silhouette and identifying features. Say what may overlap and what may not.
- Treat generated turnarounds as visual design studies. If exact cross-view
  geometry is required for manufacturing, animation, or 3D reconstruction, use
  a shared 3D/deterministic source rather than claiming prompt-level precision.

Prefer a DAG for a documented family: independent siblings can run in parallel,
failed nodes can be rerun by ID, and accepted outputs do not need regeneration.
Run `--dry-run` first and preserve the task spec as the prompt manifest.

### Review the family, not only each image

API success means generated, not accepted. After the run:

1. Verify expected count, dimensions, names, metadata, and duplicate hashes.
2. Build an overview/contact sheet grouped by dimension. Family-level drift is
   easier to see side by side than in isolated previews.
3. Review invariant fidelity, sibling differentiation, composition, cropping,
   prop interference, and declared variation compliance.
4. Quarantine rejected or obsolete references and outputs so future batches do
   not consume them accidentally.
5. Freeze accepted nodes and rerun only failures or visual outliers. If the
   canonical reference changes, invalidate every derivative that consumed it.

## Common mistakes

| Mistake | Fix |
|---|---|
| Writing "长宽比 16:9" in the prompt AND passing `-r 16:9` | Pass `-r` only; the script handles ratio. |
| Expecting 4K from openai/302/openrouter | The official `size` enum tops out at 1536x1024 (~1.57MP), and relays often ignore `size` outright. For real 4K use `-p 147ai -m gemini-3-pro-image-preview` with `GENIMAGE_IMAGE_SIZE=4K` (measured 16.9MP); `siliconflow` with a large `image_size` is the other honored-resolution route. |
| `GENIMAGE_IMAGE_SIZE=4K` on a 147ai **flash** model | Silently ignored — flash returns ~1MP at every tier. The tier only works on `gemini-3-pro-image-preview`. |
| `--ref` expecting identical behavior across providers | openai/302 = OpenAI edits; openrouter = chat; siliconflow = image_prompt; volcengine = Ark Base64 `image[]`. Results differ. |
| Using `doubao-seedream-5-0-pro` from the console URL | Use the full Model ID `doubao-seedream-5-0-pro-260628`, and activate it for the account that owns `ARK_API_KEY` first. |
| Chaining every sibling from the previous output | Reference the same canonical master from each independent node to avoid cumulative drift. |
| Asking for consistency with adjectives only | Repeat an explicit invariant/variation/scene/negative contract in every sibling prompt. |
| Treating a generated turnaround as exact geometry | Use it as a visual study; use 3D or another deterministic source for exact cross-view structure. |
| `--background` on Seedream | Hard-refused client-side before the billed call. Use the chroma-key workaround. |
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
**revoke it immediately**. Existing Seedream installs may keep
`ARK_API_KEY` in `~/.seedream-config.json`; it remains a read-only fallback, while
environment/`.env` configuration takes precedence for new setups.

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
