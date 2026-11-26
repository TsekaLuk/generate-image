# Playbook: Commercial & Product Photography

> **Core rule:** Escape the "AI plastic look" with **real studio lighting physics, explicit optical lens specs, and tactile surface micro-textures** — never vague buzzwords like "photorealistic, 8k, masterpiece".

## 1. Pre-Prompt Commercial Brief
Capture before compiling:
1. **Hero Product & Material Truth:** Exact materials per part (e.g. *matte bead-blasted anodized aluminum body, translucent amber borosilicate glass, brushed brass knurled dial, woven charcoal fabric*).
2. **Use Context:** E-commerce packshot (clean studio plinth), lifestyle tabletop (environmental storytelling), or hero campaign key visual (dramatic rim lighting).
3. **Copy / UI Safe Zone:** Reserve explicit negative space (e.g., left 35% clean backdrop or upper 25% uncluttered area) when the asset will carry marketing headlines.

## 2. Optical & Lighting Vocabulary That Models Honor
- **Camera & Lens Physics:**
  - Packshot / jewelry / cosmetics: `100mm macro lens at f/8–f/11, tack-sharp edge-to-edge product focus, medium-format studio capture`
  - Hero editorial with bokeh: `85mm prime lens at f/2.8, crisp focus on product logo/texture, smooth natural background falloff`
  - Flat-lay / catalog grid: `overhead 90-degree orthographic flat-lay, 50mm lens, zero perspective distortion`
- **Lighting Physics (Single-Source Realism Over "AI Glow"):**
  - Prefer **single-source natural directional lighting** (`late-afternoon architectural window raking light`, `diffused overcast north skylight`, `soft natural fall-off with deep ambient occlusion in crevices`, `subtle environmental color bounce off matte stone/wood`) — NEVER omnidirectional flat studio glare or neon edge glow!
  - `soft grounded contact shadow directly beneath the base` (prevents "floating pasted object" look)
  - **Tactile Physical Friction & Micro-Imperfections:** Explicitly describe uncoated paper fiber tooth, soft ink soak into textured stock, natural textile weave, subtle matte metal micro-patina, and off-axis editorial cropping (objects bleeding naturally past frame edges or held by a human hand) — ban waxy CGI perfection and dead-center Canva catalog symmetry!
- **Editorial Pigment Harmony (60-30-10):**
  - 60% low-saturation architectural/organic surface (unbleached cotton, honed limestone, raw plaster, muted warm concrete)
  - 30% product body & restrained tonal context
  - 10% nuanced mineral/ink pigment accent (pull back from harsh max-saturation digital RGB primaries `#0047FF`/`#FF0000` and backlit glow)

## 3. Six-Layer Prompt Blueprint
1. **Deliverable & Hero Subject:** Exact product geometry, proportion, and per-part surface finish (`matte`, `brushed`, `satin`, `micro-textured`, `subsurface translucent`).
2. **Staging & Composition:** Podium/surface geometry, asymmetrical rule-of-thirds placement, intentional negative space for typography.
3. **Camera & Optics:** Focal length, aperture, perspective angle, depth-of-field plane.
4. **3-Point Studio Lighting:** Key modifier + direction, rim/edge highlight, fill ratio, grounded contact shadow.
5. **Color Theory & Environment:** Exact palette harmony + 1–2 restrained contextual props (never busy clutter).
6. **Targeted Negatives:** *"No plastic skin/surface sheen, no artificial HDR glow, no floating product without contact shadow, no deformed labels, no extra fingers/clutter, no watermarks."*

## 4. High-Leverage DAG Pattern (1 Product → Full Campaign Kit)
When a user provides 1 product photo (`--ref`) or asks for a product campaign:
- **Stage 1 (`anchor`):** Lock clean studio hero shot (`gpt-image-2.6-sunburst` for label/logo fidelity).
- **Stage 2 (`matrix` fan-out via `@anchor`):** Expand `ratio × scene` (e.g. `1:1` e-commerce packshot, `4:5` Instagram hero, `16:9` website banner with left text safe-zone, `9:16` vertical story ad) across 2–3 lighting moods.
- Always run `--resume` and inspect `contact_sheet.png` to verify logo/geometry fidelity before presenting `gallery.html`.
