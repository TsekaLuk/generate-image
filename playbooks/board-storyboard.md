# Playbook: N-in-1 Exploration Boards & Short-Drama (短剧) 3×3 Storyboards

> **Why Boards are a superpower:** Generating 6 or 9 panels on ONE canvas uses a **single latent pass** — giving you either (A) **6× faster concept exploration** in 1 call, or (B) **95%+ cross-shot character/wardrobe/lighting coherence** for short dramas & video keyframes!

---

## Workflow A: N-in-1 Concept Exploration Board (方向板 · N 选 1)
Use when the user's creative direction is open ("帮我想几个视觉方向 / 找找感觉").

1. **Generate 1 Board (`2x3` or `3x3`)** with explicit cell mapping (`A`..`F` or `A`..`I`):
   - State exact grid geometry (`a clean 2-row by 3-column 6-panel concept exploration board, equal-sized cells separated by thin 2px dark hairline dividers`).
   - Assign **one genuinely distinct visual direction** to each cell (vary composition, color school, lighting, medium — not trivial tweaks!).
   - Put a small unobtrusive label (`A`..`F`) in each cell's top-left corner ONLY if presenting the board directly to a user; **omit labels** if you plan to `grid:` slice and feed cells into `--ref`!
2. **Agent Visual Selection:** Inspect the single board image with native vision (`read_file`), evaluate which cell best serves the user's intent, and pick the winner (say `C`).
3. **Slice & Fan-Out:** Use `grid: {rows: 2, cols: 3, trim_pct: 2.0}` (or `generate-image-slice`) → feed `@board:C` into downstream DAG nodes to expand into full-res deliverables!

---

## Workflow B: Short-Drama (短剧) 4-Step Industrial Storyboard Pipeline
Use for short dramas, MV / commercial scripts, narrative animation, or feeding keyframes into video models (Kling / Sora / Runway / Wan).

### Step 1 · Character Bible / 定妆照 (`stage: anchors`)
Lock character identity BEFORE generating any scene shots. Write concrete visual anchors, never vague adjectives:
- **Identity DNA:** exact age/gender/ethnicity, facial bone structure, eye/brow shape, hair length/style/color, 1 unmistakable signature detail (scar, mole, earring, glasses).
- **Layered Wardrobe Lock:** explicitly separate `inner layer` + `outer layer` + `accessories` (e.g., *charcoal turtleneck under a weathered olive trench coat, thin silver watch on left wrist*). Repeat verbatim in every downstream shot.
- Clean neutral studio backdrop, natural skin texture (no AI plastic gloss).

### Step 2 · 3×3 Latent-Coherent Storyboard Grid (`stage: board`, `grid: 3x3`)
Reference `@character_sheet` (`refs: ["@char"]`), and specify **all 9 shots explicitly** in reading order (left→right, top→bottom) with cinematic shot types:
- **Frame 1:** Wide establishing shot (location, time, weather, spatial geography)
- **Frame 2:** Medium shot introducing character action in environment
- **Frame 3:** Over-the-shoulder (OTS) dialogue / tension framing
- **Frame 4:** Medium close-up (MCU) emotional beat / expression shift
- **Frame 5:** Extreme close-up (ECU) eyes or symbolic prop detail
- **Frame 6:** Low-angle heroic / confrontational shot
- **Frame 7:** High-angle / top-down vulnerability or spatial overview
- **Frame 8:** Side profile or three-quarter rear tracking shot
- **Frame 9:** Dynamic full-body climax / turning-point pose

**Mandatory Grid Hygiene Suffix:**
> *"Strict 3-by-3 uniform grid layout, 9 equal-sized rectangular panels separated by thin hairline black dividers, read left to right top to bottom. Identical character appearance, layered wardrobe, color grade, and cinematic lighting continuity across all 9 panels. No text, no panel numbers, no captions, no speech bubbles, no watermarks."*

- **Tip on aspect ratio:** Use `-r 9:16` for vertical short-drama boards (each sliced cell keeps 9:16 portrait proportion!) or `-r 16:9` for widescreen cinema boards (each sliced cell keeps 16:9 landscape proportion!).
- **Model pick:** `gpt-image-2.6-sunburst` gives tighter panel alignment; for ultra-sharp direct slicing without re-rendering, `-p 147ai -m gemini-3-pro-image-preview` at `4K` yields ~1800px per cell.

### Step 3 · Deterministic Auto-Slice (Zero Cost)
Declare `grid: {rows: 3, cols: 3, trim_pct: 2.0, labels: ["1","2","3","4","5","6","7","8","9"]}` directly on the `board` node in the DAG YAML. The engine automatically crops `board_1.png .. board_9.png` right after generation!

### Step 4 · Full-Res Standalone Keyframe Fan-Out (`stage: keyframes`)
Use a `foreach:` or `matrix:` block in the same DAG where each keyframe node takes **`refs: ["@board:{{shot.cell}}", "@char"]`**:
- Re-renders each low-res cropped panel into a crisp full-resolution standalone `9:16` or `16:9` production keyframe (preserving the exact framing/pose from `@board:k` AND exact facial fidelity from `@char`)!
- Inspect `contact_sheet.png` once with native vision → rerun any outlier with `--only kf_5 --resume` → deliver final `gallery.html` + clean keyframes folder ready for image-to-video!

See runnable template: [`examples/short-drama-storyboard.yaml`](../examples/short-drama-storyboard.yaml).
