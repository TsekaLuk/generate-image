# Playbook: Infographics & Knowledge Diagrams

> **Core rule:** An image model cannot hallucinate domain facts, causal chains, or key parameters you left out. **Ground the knowledge first, then compile the visual layout.**

## 1. Pre-Prompt Knowledge Extraction (Mandatory)
Before writing a single visual adjective, extract an **Information Brief** from the conversation/codebase/research:
1. **Thesis (1 short headline):** Exact quoted title (≤ 8 Chinese chars or ≤ 5 English words).
2. **Structure Type (pick ONE):**
   - **Sequential / Timeline / Pipeline** — left-to-right or top-to-bottom 3–6 numbered stages with directional connectors.
   - **Bento Grid Knowledge Map** — 3–5 modular cards (1 large hero card + stacked supporting cards) for pillars/concepts.
   - **Mechanism / Exploded Callout** — central focal illustration with 4–6 numbered pointer callouts.
   - **Split-Screen Comparison** — Before vs After, A vs B, aligned row-by-row contrast.
   - **Hub-and-Spoke / Architecture** — central core node radiating to 4–6 labeled subsystems.
3. **3–6 Concrete Information Points:** Each point = `[Short Exact Label]` + `[1 concrete visual metaphor]` + `[optional key metric/arrow]`. Never dump paragraphs.
4. **Typography Quota:** Wrap every on-image string in quotes (`"..."`). Keep labels ≤ 4–6 words; append *"render only the specified text strings, crisp legible typography, no gibberish filler text"*.

## 2. Model & Parameter Selection
- **Dense text / strict layout / architecture:** `-m gpt-image-2.6-sunburst` (higher layout planning precision) or `-p 147ai -m gemini-3-pro-image-preview` (`GENIMAGE_IMAGE_SIZE=4K` when fine labels need 16MP resolution).
- **Fast concept / clean 3-step visual:** default `gpt-image-2.6-flare`.
- **Aspect ratio:** `-r 16:9` for slides/horizontal flow, `-r 3:4` or `-r 9:16` for vertical social/mobile knowledge cards, `-r 4:5` for editorial bento grids.

## 3. Six-Layer Prompt Blueprint
1. **Deliverable & Topic:** `"A clean Swiss-editorial technical infographic titled \"...\" explaining [mechanism/topic]."`
2. **Layout & Reading Flow:** Explicit grid geometry (`4-card bento grid`, `5-step horizontal pipeline left-to-right`, `centered exploded diagram with 6 numbered callouts`), generous whitespace (≥ 25%).
3. **Concrete Information Nodes:** Enumerate each section's exact quoted label, visual metaphor icon/illustration, and causal arrows (`A → B → C`).
4. **Typography Hierarchy:** Bold geometric sans-serif title at top; crisp medium subheaders; clean short callout labels; high text-to-background contrast.
5. **Visual Style & 60-30-10 Palette:** Flat modern editorial vector (Medium / Stripe / Swiss print school), 60% clean warm off-white or deep slate canvas, 30% structural neutral cards/lines, 10% single accent color highlighting the core mechanism.
6. **Targeted Negatives:** *"No dense paragraphs, no tiny illegible body copy, no garbled letters, no decorative clutter, no overlapping labels, no watermarks."*

## 4. Iteration & Scaling Pattern
- **Exploration Board first (1 call):** Generate a `2x2` layout-direction board (`grid: 2x2`) comparing Bento vs Flowchart vs Exploded vs Split-Screen, inspect via vision, slice/pick the clearest layout, then render full-res with `gpt-image-2.6-sunburst`.
- **Multi-slide Deck (DAG):** Define `blocks.style` + `blocks.negatives` once, expand a `foreach:` list of slides sharing identical palette, stroke weight, and card radius.
