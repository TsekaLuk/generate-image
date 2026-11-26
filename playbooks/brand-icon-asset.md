# Playbook: Brand Icons, UI Assets & Transparent RGBA Stickers

> **Core rule:** GPT Image 2.6 natively outputs **true 8-bit RGBA transparent PNGs** (`--background transparent`) on both `openai` and `302ai`. Never fall back to green-screen chroma-keying on 2.6!

## 1. When to Use `--background transparent`
- App icons, UI badges, feature illustrations, mascot cutouts, e-commerce stickers, floating 3D objects, brand monograms.
- **Hard constraint 1:** `--background transparent` works on PNG stills only — **do not combine with `--gif`**.
- **Hard constraint 2 (CRITICAL — Prevents Logo Drift):** **NEVER pass a `--background transparent` RGBA PNG as `--ref` into downstream img2img nodes!** GPT Image 2.6 outputs transparent pixels with `(0..1, 0..1, 0..1, 0)` RGB; upstream vision preprocessors can flatten alpha onto black and **erase dark/black strokes** from your logo. Always lock your canonical `--ref` master on a **clean opaque solid white background**, and generate the transparent RGBA asset as a **leaf deliverable** derived from that opaque master!
- **Hard constraint 3 (Opaque Scenes):** For photographic/architectural scenes with bright highlights or windows on GPT Image 2.6, explicitly pass `--background opaque` (or `background: "opaque"` in DAG) so `auto` never accidentally leaves semi-transparent alpha pixels along bright light edges.
- **QA habit:** Always inspect transparent outputs in `gallery.html` using the **Checkerboard / Light / Dark backdrop toggle** to catch any white halo or clipped shadow before delivery.

## 2. Consistency Contract for Icon & Asset Families
A set of 8–50 icons looks amateurish the moment stroke weight, lighting angle, or padding drifts. Lock a reusable `blocks.icon_dna` in your DAG YAML:
- **Projection & Viewpoint:** e.g. `strict front orthographic 2D view` OR `consistent 30-degree isometric 3D view`.
- **Geometry & Stroke System:** e.g. `uniform 4px rounded stroke weight, consistent 16% corner radius, clean geometric primitives` OR `soft matte 3D clay/vinyl sculpt with smooth beveled edges`.
- **Unified Light Source (for 3D/shaded sets):** e.g. `fixed top-left soft key light at 45°, subtle cool bottom-right bounce fill`.
- **Canvas Framing & Padding:** `centered object occupying ~75% of canvas with generous equal transparent margin on all four sides, zero edge clipping`.
- **Clean Alpha Isolation:** `isolated single object on a completely transparent background, NO backdrop plate, NO cast floor shadow, NO outer glow, NO floating dust`.

## 3. Die-Cut Sticker Sheets (N-in-1 + Auto-Slice)
For sticker packs / emoji sets / badge collections:
- **Option A — Individual Assets via DAG `foreach:` (Highest resolution & cleanest alpha):**
  - Generate 1 canonical **opaque white-background** icon (`@anchor_icon_opaque`) → visually verify style → fan out 10–30 sibling icons (plus the transparent leaf version of the anchor) referencing `@anchor_icon_opaque` with `blocks.icon_dna` + `--background transparent`.
- **Option B — Fast `3x3` Sticker Sheet (`grid: 3x3` + `--background transparent`):**
  - Prompt: *"A crisp 3x3 grid die-cut sticker sheet of 9 distinct [subject] expressions/items, read left to right top to bottom: (1)..., (2)..., ..., (9)... Glossy vinyl finish with uniform crisp white die-cut contour border around each sticker, ample even transparent spacing between every cell, strictly aligned to a 3x3 grid, isolated on a transparent background, no grid lines, no text labels."*
  - Set `grid: {rows: 3, cols: 3, trim_pct: 1.0}` in DAG → auto-slices into 9 standalone transparent RGBA sticker PNGs!

## 4. Targeted Negatives
*"No solid background box, no white rectangular card behind the icon, no checkerboard pattern drawn inside the image, no long drop shadows cut off by canvas edges, no inconsistent perspective, no random text."*
