# Playbook: Coherent Character & Storybook Series

> **Core rule:** Lock identity & visual medium in shared DAG `blocks`, vary only ONE declared dimension per sibling, and fan out in a **star topology** from one approved canonical anchor (never chain A→B→C→D!).

## 1. Curated Style Blocks (Pick ONE for the Entire Series)
Reuse verbatim inside `blocks.style` across every panel:
- **`watercolor-storybook`:** Hand-painted watercolor picture-book illustration, soft pigment washes with organic bleeding edges, subtle warm off-white cotton paper grain, thin sepia ink outlines, generous breathing whitespace, gentle diffused morning light. Avoid hard digital vector edges or neon saturation.
- **`crayon-cozy`:** Warm colored-pencil and soft wax-crayon strokes with visible directional grain over light watercolor underwash, cozy palette (cream yellow, muted rose, caramel brown, moss green), tactile paper tooth, soft ambient light, hand-drawn wobble, children's book cover finish.
- **`ghibli-warm`:** Hand-drawn anime film background aesthetic, lush painterly botanical detail, warm golden-hour or dawn rim lighting, soft atmospheric perspective, expressive rounded character silhouettes, rich gouache sky clouds. Avoid sterile 3D CGI sheen.
- **`papercraft-collage`:** Tactile multi-layered cut-paper collage illustration, distinct matte cardstock layers with visible paper thickness and soft realistic cast drop-shadows, 2–3 clear parallax depth planes, soft overhead studio light. Avoid digital gradients.
- **`kawaii-pastel`:** Japanese kawaii pastel illustration, rounded chibi proportions (1:1.5 head-to-body), soft candy palette (cream pink, mint, butter yellow, lavender), minimalist dot eyes and gentle blush, clean uncluttered backdrop.
- **`flat-vector-editorial`:** Modern geometric flat editorial illustration (The Verge / Medium school), bold clean color blocks without heavy outlines, restrained 3–4 complementary colors, subtle risograph grain accent, graphic negative space.

## 2. Four-Block Consistency Contract (Mandatory for Series DAGs)
Split every series prompt (or `spec:`) into four explicit blocks:
1. **`blocks.invariant` (Identity Lock — verbatim everywhere):** Species/gender/age, hair/eyes, exact head-to-body ratio, and **1 unmistakable visual anchor prop** (e.g., *a frayed crimson wool scarf*, *oversized round brass spectacles*).
2. **Declared Variation (unique per node):** The ONE intentional change — pose, emotion, camera shot (`cover-hero` with top 30% title safe zone / `establishing-wide` subject at 1/6 scale / `character-closeup` upper-thirds eyes / `introspective-mood` vast atmospheric negative space), or scene beat.
3. **`blocks.style` + `blocks.scene` (Render Contract — verbatim everywhere):** Medium, lighting temperature, palette, margin/framing rules.
4. **`blocks.negatives` (Anti-Drift Constraints):** Specific failure modes (*no extra limbs, no changing scarf color, no random text, no shifting art style*).

## 3. Star Topology vs Serial Chain
- **Star fan-out (default):** Generate `anchor` first (`--only-roots`) → visually verify character DNA → every sibling passes `refs: ["@anchor"]`. Zero cumulative drift across 10–100 panels.
- **Serial chain (`@prev`):** Use ONLY when temporal scene continuity (e.g. a continuous room transformation) matters more than returning to exact canonical identity, and re-anchor every 3–4 steps with `refs: ["@anchor", "@prev"]`.

*(Legacy scene fill-in templates remain available in `templates.md`.)*
