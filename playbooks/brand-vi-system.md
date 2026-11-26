# Playbook: Commercial-Grade Brand VI Systems (Meta-Cognitive Hybrid Pipeline)

> **Meta-Cognitive Principle (Read First):**
> **Engineering Compliance ≠ Commercial Design Excellence.** Zero typos, zero drift, clean grids, and valid Pantone codes only take a brand identity from **0 → 60 points**. What makes a client actually pay — and lets work stand beside Behance Featured, 站酷首页, Brand New, Pentagram, or Batoer — is **style-agnostic commercial craftsmanship**:
> 1. **Right Tool for Each Cognitive Layer:**
>    - **NEVER** hand-code primitive SVG `<rect>` shapes as a brand's signature logo mark, and **NEVER** type raw OS system fonts (`Songti SC` / `PingFang`) as a bespoke brand logotype!
>    - Use **AI multi-direction visual exploration (`grid: 2x3` / `3x3`, `gpt-image-2.6-sunburst`)** to achieve genuine sculptural originality, custom hand-lettered CJK/Latin typography, and iconic brand symbols/IPs.
>    - Immediately **vectorize winning flat marks & handcrafted logotypes** via **`trace_svg: true`** (`potrace` / `vtracer` → smooth multi-color Bezier `.svg`) and isolate **clean RGBA cutouts (`--background transparent`)** for downstream editorial composition.
> 2. **Never Overfit to Reference Styles — Calibrate to Universal Quality Invariants:**
>    - Every industry deserves its own authentic aesthetic (quiet poetry, brutalist typography, neo-pop 3D IP, high-fashion editorial). Judge quality by **universal invariants**: *silhouette memorability, handcrafted typographic originality, macro/micro scale tension, living ecosystem richness, and narrative showcase pacing*.
> 3. **Adversarial "3-Second Studio Portfolio Swap Test":**
>    - Before accepting ANY creative anchor or final showcase, name its **top 3 weaknesses** compared to a top working studio's portfolio. If a Design Director would clock it as "AI mockup slop" or "rigid programmer PPT" within 3 seconds → **HARD REJECT and iterate!**

---

## The 5-Stage Production Brand VI Pipeline (`generate-image` v3.2)

### Stage 1 · High-Ceiling Creative Exploration Boards (`kind: generate`, `grid: 2x3`)
Do NOT settle for 1 timid guess. Run two dedicated exploration boards first:
- **Board A — Brand Mark & Custom Handcrafted Logotype (`grid: 2x3`, `gpt-image-2.6-sunburst`):**
  Explore 6 genuinely distinct, high-concept commercial directions: e.g., (1) custom sculpted Chinese character architecture where the brand name itself IS the logo, (2) iconic negative-space animal/cultural totem, (3) modernist seal/monogram with bespoke calligraphy tension, (4) kinetic optical aperture / geometric sculpture, (5) avant-garde typographic ligature, (6) iconic minimal silhouette.
- **Board B (when brand benefits from a character/totem/super-symbol) — Signature Brand Icon / 3D Tactile Mascot or Cultural Object (`grid: 2x3`):**
  Explore 6 memorable sculptural silhouettes with unmistakable personality and silhouette recognition (never generic stock spheres or clichés).
- **[HARD VISUAL GATE #1]:** Inspect every cell at full resolution. Apply the **3-Second Portfolio Swap Test**. If ALL 6 cells look generic or weak, refine the conceptual angle and regenerate the board BEFORE proceeding!

### Stage 2 · Lock, Refine, Vectorize & Isolate (`trace_svg: true` + Leaf RGBA Cutout)
- **Opaque Canonical Masters (`ratio: 1:1` / `16:9`, `background: opaque`, `trace_svg: true`):**
  Refine the winning graphic mark AND winning handcrafted custom logotype to razor-sharp flat perfection on solid pure white (`#FFFFFF`). `trace_svg: true` automatically exports smooth multi-color Bezier **`.svg` vector masters** alongside the `.png`!
- **Transparent RGBA Cutouts (`background: transparent`, LEAF nodes — NEVER feed RGBA as `--ref`!):**
  Generate crisp transparent PNG cutouts of the locked mark, custom logotype, and sculptural IP/super-symbol so Stage 5's editorial layout can layer them **breaking across section frames and huge display typography**!

### Stage 3 · Living Brand Ecosystem Expansion (`kind: generate`, Star Topology from Opaque Anchors)
Move far beyond "boring office stationery" (cards + lobby + book). Build a **living, commercially rich brand universe** tailored to the client's actual industry:
- **Design Process & Motion/Expression Sheet (`grid: 3x3` or `4x4`):** Black-and-white expressive concept sketch / motion script / graphic motif matrix (proves design rigor & system extensibility).
- **Merch, Die-Cut Stickers & Collectible Objects:** Die-cut sticker pack wall, collector's acrylic display sculpture / vinyl art toy / physical artifact, curated packaging & tote bag family shot.
- **Editorial Key Visuals & Campaign Scenes:** 2–3 high-emotion campaign scenes / 3D art-directed environments / fine-art cinema stills (tailored to brand DNA, ZERO garbled micro-text).
- **Real-World Spatial & Digital Contexts:** Tactile print collateral, exhibition/pop-up installation or restrained architectural signage (14%–22% wall width), and authentic digital product / UI ecosystem.

### Stage 4 · Production Print & UI Flat Artwork (`kind: render`, ¥0)
Composite the **vectorized/isolated AI-crafted mark + handcrafted custom logotype** (NOT raw system fonts!) with crisp body/metadata typography, real contact info, real exhibition/product schedules, barcodes/QR codes, and Pantone/CMYK/RGB/HEX production specs. Stage key physical mockups directly from these finished flat artworks (`background: opaque`) when photographic realism is required.

### Stage 5 · Behance / 站酷 Long-Scroll Case Study (`kind: render` sections → `kind: stitch`, ¥0)
NEVER present a commercial VI as 4 sterile gray-bordered PPT slides! Assemble **8–10 full-bleed rhythmic vertical chapters** (`width: 1440px @2x`), then stitch them seamlessly via `kind: stitch` into ONE master **`CASE_STUDY_LONG_SCROLL.png`** (plus printable PDF):
- **Rhythmic Visual Grammar:**
  - Alternate full-bleed **Deep Obsidian / Pure White / High-Impact Brand Color** chapters for cinematic scroll momentum.
  - Use **oversized edge-to-edge background display typography** (`140px–240px`) layered BEHIND crisp **RGBA transparent cutouts** that physically break section borders!
  - Tell a persuasive commercial arc: **01 Hero Impact Cover → 02 Brand Thesis & Pain Points → 03 Mark & Handcrafted Logotype Craftsmanship → 04 Color, Typography & Supergraphic Rhythm → 05 Brand Symbol / IP & Sketch Derivation (`3×3` Motion/Icon Sheet) → 06 Packaging, Stickers & Collectible Merch → 07 Editorial Posters & Spatial Experience → 08 Digital Product & Campaign Scenes → 09 Closing Colophon**.
