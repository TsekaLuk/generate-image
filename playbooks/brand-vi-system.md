# Playbook: Meta-Cognitive Brand & Visual Identity Systems (Archetype-Agnostic)

> **Core Meta-Cognitive Law (Read First):**
> **Never conflate a universal *Quality Bar* with a single industry's *Visual Style*.**
> An AI Agent PaaS (`Linear` / `Vercel` / `Anthropic`), a To-B/To-G institutional media group, a luxury fragrance house, and a To-C new-retail consumer app live in **completely different visual universes** — with completely different symbols, color physics, typography, touchpoints, and presentation grammars.
>
> **Anti-Few-Shot-Overfitting Rule:** When a user shares reference links or screenshots to critique design quality, extract ONLY the **style-agnostic quality invariants** (*originality, craft ceiling, visual tension, real-world usability, narrative conviction*). **NEVER blindly transplant the reference's industry tropes** (e.g., 3D vinyl mascots, sticker packs, or consumer app empty states) onto an unrelated business model!

---

## 1. Mandatory 4-Axis Brand Diagnosis (Before Generating a Single Pixel)

Explicitly establish these 4 axes from conversation context (or ask 1 crisp clarifying question if the business model is genuinely ambiguous):

1. **Transaction Topology:** `To-C Consumer` · `AI SaaS / PaaS / Agent / DevTools` · `To-B Enterprise / Industrial` · `To-G / Institutional / Cultural` · `B2B2C Dual-Register`.
2. **Decision-Maker Psychology:** What makes the real buyer/user trust or desire this brand? *(e.g. technical authority & speed for developers; institutional permanence & cultural gravitas for B2G/B2B; emotional magnetism & social currency for To-C).*
3. **Real-World Touchpoint Gravity:** Where does this organization **actually** meet people? Derive the deliverable list strictly from real touchpoints — **never run a fixed copy-paste mockup checklist!**
4. **Domain-Native Gold-Standard Benchmarks:** Identify 2–3 real contemporary leaders *inside this exact sector* to calibrate aesthetic judgment before starting Stage 1.

---

## 2. Archetype Touchpoint & Visual Grammar Matrix

The **exact same `generate-image` v3.2 primitives** (`grid` exploration → `trace_svg` Bezier vectorization → opaque star-topology generation → `kind: render` precision layout/UI/specs → `kind: stitch` narrative presentation) instantiate totally different brand worlds depending on the archetype:

| Archetype | Core Identity Language | Authentic Visual System (NO Foreign Tropes) | High-Value Real Touchpoints |
|---|---|---|---|
| **AI SaaS / PaaS / Agent / DevTools** *(Benchmarks: Linear, Vercel, Anthropic, Stripe, Raycast, Runway)* | Razor-sharp minimal geometric/optical symbol + bespoke neo-grotesque / mono wordmark | Optical depth, restrained dark/light surface tokens, hairline borders, procedural light-fields / data-flow schematics, kinetic precision (**NO cartoonish mascots** unless explicitly consumer playful AI) | App Icon / Favicon · Vector Wordmark · Dark/Light UI Token Sheet · Launch Hero & Bento Feature Cards · CLI / SDK / Docs Header · Announcement OG Cards · Developer Conference Keynote & Lanyard |
| **To-B Enterprise / Industrial / Finance** *(Benchmarks: Pentagram, Wolff Olins, Collins, Landor)* | Monolithic sculptural emblem + authoritative custom architectural logotype | Structured modular grid, high-contrast executive palette, technical diagram/chart language, tactile architectural materiality | Vector System & Print Manual PDF · Executive Pitch Deck Covers · Annual Report & Whitepaper · Summit Keynote Stage Backdrop · Restrained Architectural Signage (14%–22% wall width) · Business Stationery |
| **To-G / Cultural Institution / Public Media** *(Benchmarks: M+ Museum, Studio Dumbar, UCCA, A24, 雅昌, 靳刘高)* | Contemporary distilled cultural/architectural emblem + bespoke calligraphic or editorial wordmark | Editorial typographic poise, curated fine-art/documentary photography, architectural wayfinding grammar, disciplined negative space | Exhibition / Forum Main Visual Poster · Hardcover Monograph / Catalog · Stage & Spatial Wayfinding · Official Credentials · Editorial Digital Portal · Print-Ready VI Manual PDF |
| **B2B2C Dual-Register** *(e.g. Media Group serving Gov/Enterprise + Public; Healthcare Platform)* | **One unbreakable core mark & grid** powering **two calibrated registers**: Calm Institutional Core (B/G) + Expressive Campaign Layer (C) | Strict rules defining what stays invariant (mark, wordmark, core grid) vs what flexes between partner decks and public campaigns | Dual-Register Identity Spec · Partner/Forum Keynote & Report (B/G register) + Public Exhibition / Digital Product / Campaign Visuals (C register) |
| **To-C Consumer / New Retail / Lifestyle / IP Apps** *(Benchmarks: Aesop, Teenage Engineering, Batoer, Duolingo, Pop-Mart)* | Iconic super-symbol, bespoke handcrafted display logotype, and/or charismatic 2D/3D brand IP | High-voltage brand super-color, tactile materiality, playful or lifestyle-driven storytelling, frame-breaking visual energy | Packaging & Unboxing Family · Storefront / Pop-up / Street Campaign · Character/Motion Sheet & Stickers (if IP-driven) · Social Campaign Visuals · Consumer App UI & Empty States |

---

## 3. Style-Agnostic Tool Routing (Right Tool for Each Cognitive Layer)

Regardless of archetype, route each cognitive layer to the tool with the highest quality ceiling:

1. **High-Ceiling Creative Ideation (`kind: generate` + `grid: 2x3` / `3x3`, `gpt-image-2.6-sunburst`):**
   - Use for **original graphic emblems, handcrafted custom CJK/Latin logotypes, procedural optical shaders, editorial photography, tactile 3D artifacts, architectural spaces, and (when domain-appropriate) character design**.
   - **Hard Rule:** NEVER degrade creative ceiling by hand-coding primitive `<rect>` SVGs for a signature logo mark or passing off unmodified OS system fonts as a bespoke brand wordmark!
2. **Vector Productionization (`trace_svg: true` + Leaf RGBA Cutouts):**
   - Refine winning flat graphic marks and handcrafted logotypes on 100% solid pure white (`#FFFFFF`, `background: opaque`) with **`trace_svg: true`** → automatically outputs smooth multi-color Bezier `.svg` masters (`potrace` / `vtracer`).
   - Isolate transparent RGBA versions (`background: transparent`) strictly as **leaf deliverables** — NEVER feed RGBA PNGs into downstream img2img `--ref`!
3. **Deterministic Typography, Real UI & Production Specs (`kind: render`, ¥0):**
   - Render genuine **product UIs (dashboards, terminals, bento cards, web portals), print-ready real-copy layouts (posters with real schedules, reports, cards with real contact hierarchy), and mathematical VI spec sheets / multi-page PDFs (Pantone / CMYK / RGB / HEX / clearspace / min sizes / Don'ts)** using HTML/CSS + inline vectorized SVG + upstream AI visual assets (`{{refs.<id>}}`).
4. **Physical Scene Staging (`kind: generate`, `background: opaque`):**
   - When photographic physical context is needed, stage directly from **finished flat artwork** (`@poster_flat`, `@report_flat`, `@card_flat`, `@web_flat`) so typography, hierarchy, and real information density transfer with zero font drift.
   - Keep environmental signage architecturally restrained (**14%–22% wall width**).
5. **Narrative Showcase Assembly (`kind: render` chapters → `kind: stitch`, ¥0):**
   - Match the presentation grammar to the brand's archetype (crisp technical product-launch story for AI PaaS; gallery/architectural monograph cadence for To-B/To-G/Cultural; high-energy rhythmic long scroll for To-C) — NEVER force every client into one fixed template!

---

## 4. Universal 5-Invariant Quality Gate (Applies to Every Industry)

Before shipping ANY anchor or final delivery, audit against all 5 style-agnostic invariants:
1. **Domain-Truth Alignment:** Would an insider in *this specific industry* immediately recognize the visual language as native, credible, and contemporary?
2. **Craft Ceiling & Originality:** Is the core mark / wordmark / visual metaphor genuinely distinctive and trademark-worthy (not a stock cliché or hand-coded primitive)?
3. **Zero Drift & Real Usability:** Exact mark/logotype fidelity across every deliverable; real `.svg` vectors, real production color/type specs, real usable information density (no empty placeholder mockups).
4. **Compositional Tension & Rhythm:** Deliberate macro/micro scale contrast, intentional negative space, cohesive palette discipline — never monotonous gray-bordered PPT grids.
5. **Adversarial 3-Second Benchmark Critique:** Explicitly name the **top 3 flaws** compared to the domain-matched gold-standard benchmarks chosen in Section 1. Reject and iterate until genuinely competitive.
