# Playbook: Deliverable-Grade Brand VI Systems (Hybrid Vector + Editorial + AI)

> **Core Truth:** Pure end-to-end diffusion **cannot** deliver a real Brand VI system on its own. Diffusion models hallucinate different fonts on every asset (Font Drift), fake mathematical construction grids, omit Pantone/CMYK specs, and collapse real-world business cards/posters/passes into empty "Logo Slapping" mockups.
> **The Production Formula:** **Deterministic Vector & Typography (`kind: render`, SVG + HTML/CSS via headless Chromium)** locks the mathematical identity, custom CJK/Latin logotype, supergraphic, VI manual specs, and real print/UI artwork — while **AI Diffusion (`kind: generate`)** produces bespoke fine-art photography and stages tactile real-world editorial scenes **directly from the finished flat artwork**!

---

## 1. The 5-Layer Brand VI Architecture (Zero Logo-Slapping)

Never jump straight from a company name to slapping a generic geometric icon onto mockups. Build all 5 layers in a single hybrid DAG:

### Layer 1 · Brand Strategy & Cultural DNA (Before Any Drawing)
Define explicitly before writing a single SVG path or prompt:
- **Brand Etymology & Core Metaphor:** What makes this brand's *name* and *sector* uncopyable? (e.g., a cultural & cinema media house needs humanistic storytelling, calligraphic/editorial tension, and optical light — NOT cold real-estate stone or generic 3-polygon shapes that fail trademark registration!)
- **Trademark Distinctiveness Bar:** Ask honestly — *"If you hide the company name, can a designer tell this isn't a bookstore, elevator company, or generic geometric template?"*
- **Role of Every Palette Color (60-30-10 + Production Codes):** Every brand color MUST carry real **HEX + RGB + CMYK + Pantone** specifications, AND every defined accent color must actually earn its place across the touchpoints.

### Layer 2 · Deterministic Vector Core & Multi-Page VI Manual (`kind: render`, ¥0)
Generate mathematically exact vector masters and locked typographic combinations:
1. **Master Emblem (`svg_file`):** Exports BOTH standalone **`.svg` vector master** (print/trademark-ready) AND crisp high-DPI **`.png`** (opaque solid white master + transparent RGBA leaf).
2. **Locked Primary & Secondary Logotypes (`svg_file` / `html_file`):**
   - Lock the exact **Custom CJK Logotype + Latin Wordmark** proportions, optical baseline alignment, weight contrast, and letter-spacing in **Horizontal Lockup**, **Vertical Lockup**, and **Dark-Mode Inversion**.
   - **Rule:** NEVER let downstream diffusion re-invent Chinese or English fonts from text prompts alone!
3. **Auxiliary Visual System (Supergraphic / Dynamic Frame):**
   - Derive a distinctive graphic motif (e.g., anamorphic frame marks, seal-stamp index coordinates, optical slit rhythm, editorial grid bars) so the brand remains unmistakably recognizable **even when the logo is hidden**.
4. **True Multi-Page VI Guidelines Manual (4–6 Dedicated Sheets + Print PDF):**
   - **Sheet 01 · Mark Construction Grid:** True unit square `a` / `x` coordinate grid, exact proportional callouts (`12a × 12a`, angles, radii), Clearspace (`≥ 2a`), and Minimum Sizes (`Print ≥ 12mm / Digital ≥ 28px`).
   - **Sheet 02 · Lockup Matrix & Misuse (Don'ts):** Horizontal, vertical, monochrome, dark inversion + 4–6 concrete visual Don'ts (no stretching, no recoloring, no drop-shadows, no low-contrast crowding).
   - **Sheet 03 · Color & Typography System:** Primary + Secondary + Accent swatches with **Pantone / CMYK / RGB / HEX** + proportional bar + real CJK/Latin font specimen (`H1 / H2 / Body / Caption / Metadata`).
   - **Sheet 04 · Supergraphic & Editorial Grid Grammar:** How the auxiliary graphics divide posters, book covers, passes, and screens.

### Layer 3 · Bespoke AI Fine-Art Key Visuals (`kind: generate`, ZERO AI Text!)
Use `gpt-image-2.6-sunburst` exclusively where diffusion excels:
- Generate 2–3 signature brand imagery assets (cinema still, poetic architectural light/shadow study, cultural portrait / tactile paper-and-ink still life) with **ZERO baked-in text or logos**.
- Match the brand's actual emotional temperature (human warmth, poetic film grain, editorial authenticity — NOT sterile 3D renders).

### Layer 4 · Real Print & Digital Flat Artwork (`kind: render`, Compositing Vector + Real Copy + AI Photography)
Combine Layer 2 vectors + Layer 3 photography via `{{refs.<kv_id>}}` inside deterministic HTML/CSS templates to produce **genuinely usable, print/dev-ready flat artwork** with authentic information hierarchy:
- **Business Card (Front + Back):** Real 90×54mm layout with contact name, title, phone, email, studio address, website, subtle QR code, and locked lockup.
- **Exhibition / Screening Poster:** Real event title, bilingual subtitle, dates, venue, curatorial/production credits, supergraphic frame + bespoke Layer 3 AI key visual.
- **Festival / Media Credential Pass:** Real portrait/badge layout, pass holder name, role, credential ID (`YZ-2026-0418`), access zones (`SCREENING / PRESS / LOUNGE`), dates, and crisp vector barcode.
- **Annual Monograph / Book Cover:** Volume/issue number (`VOL.01 / 2026`), thematic title, bilingual editorial metadata, spine/cover wrap rhythm, locked lockup + supergraphic.
- **Digital Editorial Website + Mobile Screen:** Real navigation bar (`FILMS · EXHIBITIONS · ARCHIVE · JOURNAL · ABOUT`), featured screening hero with director/year/runtime metadata, interactive index, and mobile launch/editorial screen.

### Layer 5 · Tactile Physical Scene Staging (`kind: generate`, Referencing Complete Flat Artwork!)
- **Flat-First Staging Rule:** Feed the **finished Layer 4 flat artwork** (`refs: ["@03_business_card_flat"]`, `["@04_poster_flat"]`, etc.) into `gpt-image-2.6-sunburst` with **`background: "opaque"`**. Now the physical photograph preserves the **exact locked typography, exact layout grid, exact supergraphic, and realistic information density** while adding authentic paper fibers, letterpress deboss, brushed metal speculars, sunlit plaster shadows, and natural editorial atmosphere!
- **Architectural Scale Restraint (Signage Rule):** For HQ lobby / facade / gallery signage, keep the mounted lockup refined and human-scaled (**14%–22% of wall width**, generous architectural breathing space around it — NEVER a giant 40% real-estate billboard!).
- **Strict Visual QA on Every Staged Scene:** Compare every staged scene side-by-side against its Layer 4 flat artwork at full resolution (`read_file`). Reject immediately if any Chinese glyph garbles, logo geometry shifts, or staging looks like generic AI mockup slop.
