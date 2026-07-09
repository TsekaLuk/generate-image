# examples

Ready-to-edit specs for `generate-image`. Copy one and change the prompts.

## `bytedance-logos.yaml` — a real DAG run (department logo set)

10 ByteDance-style department logos in one shared visual language, generated in
parallel. Sample renders (512px) are in [`bytedance-logos/`](bytedance-logos/).

<p>
  <img src="bytedance-logos/01-engineering.png" width="120" alt="Engineering">
  <img src="bytedance-logos/04-marketing.png" width="120" alt="Marketing">
  <img src="bytedance-logos/07-finance.png" width="120" alt="Finance">
  <img src="bytedance-logos/10-data.png" width="120" alt="Data">
</p>

```bash
uv run generate-image --dag-file examples/bytedance-logos.yaml \
  -o ~/Desktop/bytedance-logos --concurrency 3
```

Each task's image → `<name>.png` (e.g. `01-engineering.png`). The tasks are
independent (no edges) so they run in parallel. To **style-lock** them to a
shared base instead, add a `00-base` task and give each department
`refs: ["@00-base"]` (see the comment atop the spec) — that turns it into a
serial → parallel DAG where every logo restyles the base.

## `prompts.txt` — batch mode

One independent image per line (a zero-edge DAG):

```bash
uv run generate-image --batch-file examples/prompts.txt --concurrency 3
```

## DAG spec quick reference

```yaml
tasks:
  - id: A                     # required, unique
    prompt: "..."             # required
    provider: openai          # optional; openai/302ai/openrouter/siliconflow
    model: gpt-image-2        # optional (default: the provider's default)
    ratio: "1:1"              # optional (default: 16:9)
    name: 01-hero             # optional filename stem (default: the id)
    depends_on: [X]           # optional explicit deps (ordering only)
    refs: ["@X", "b.png"]     # "@X" = use task X's output image (dep + img2img);
                              #        multiple @refs = a join compositing them.
```

- Edges = `depends_on` ∪ every `@id` in `refs`. Any acyclic graph is valid; cycles
  are reported at load time.
- Failure policy: `--on-failure skip` (default — skip a failed task's descendants,
  keep independent branches) or `--on-failure fail-fast`.
- Reliability (rate limit, retry, adaptive concurrency) is automatic, per provider.
- **Each task is a billed image call** — review the graph and cost before running.

> `uv run generate-image ...` uses the installed console script; `./generate.py ...`
> (the top-level launcher) works too.
