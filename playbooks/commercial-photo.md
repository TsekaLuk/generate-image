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
- **Studio Lighting Modifiers (never just "good lighting"):**
  - `large diffused overhead softbox at 45°` (clean gradient specular roll-off)
  - `vertical strip-box rim lighting tracing glass/metal edges`
  - `subtle white bounce-card fill lifting shadow side`
  - `soft grounded contact shadow directly beneath the base` (prevents "floating pasted object" look)
- **Color Harmony (60-30-10):**
  - 60% low-saturation architectural surface (warm travertine stone, raw matte concrete, soft linen)
  - 30% product body & tonal props
  - 10% high-chroma accent or specular highlight

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
