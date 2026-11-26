# Playbook: First-Principles Visual Identity & Brand Systems

> **Why there is NO fixed industry lookup table in this playbook:**
> The real world is not a 5-row enum. Two extraordinary organizations inside the exact same industry can legitimately occupy opposite aesthetic poles — and any rigid `"if sector == X → output {A, B, C}"` rule merely replaces visual thinking with stereotypes.
>
> Instead of prescribing styles or fixed mockup shopping lists, this playbook defines **the cognitive process** by which a strong creative director derives an original, credible, deliverable visual system from scratch for *any* entity.

---

## 1. Sense-Making Before Form (Deconstruct Before Drawing)

Before generating a single pixel or deciding what artifacts to produce, answer four grounded questions — using conversation context, workspace files, and **live web research** when stepping into an unfamiliar domain:

1. **Essence & Tension:** What does this organization *actually* do, believe, or push against? What single conceptual tension differentiates it from an interchangeable competitor?
2. **Real Habitat & Human Moment:** Where do real people (users, buyers, developers, citizens, audiences, partners) actually encounter this identity — and what must they *feel* in the first two seconds? *(Trust? Sharpness? Warmth? Restraint? Speed? Playfulness? Authority?)*
3. **Category Clichés to Reject:** What does the average, forgettable competitor in this space already look like? Name 2–3 overused category tropes upfront and explicitly ban them so the work refuses to regress to the statistical mean.
4. **Live Contemporary Calibration:** Ground your quality bar in **real, current, non-generic craft** — never freeze outdated templates, and **never confuse a user's quality reference with a style mandate**. Extract *craft rigor* from benchmarks, then invent a visual language native to *this* subject.

---

## 2. Derive the System & Artifact Topology Organically

A visual identity is **not** a single logo pasted onto a standard set of mockups — it is an **internally consistent visual language** where every element reinforces the same core idea:

- **Core Visual Signature:** Could be a sculpted graphic emblem, a custom handcrafted wordmark/logotype, an optical/generative visual motif, a distinctive typographic voice, a tactile material system, a character/figure — or a restrained combination. Choose *only* the elements that authentically serve the subject's habitat (never force a mascot, or forbid one, by dogma).
- **Coherent Grammar:** Define the governing rules of proportion, stroke/surface character, color physics (role & ratio, not random decoration), typographic hierarchy, and negative space so that even with the logo hidden, the work remains unmistakably attributable.
- **Native Artifact Selection:** Derive the deliverable set strictly from **where the brand actually lives**:
  - Ask: *"Which 5–10 concrete artifacts would prove to a skeptical stakeholder that this identity actually works in real life?"*
  - Give every artifact **real information density and functional purpose** (real hierarchy, real copy/UI/metadata/specs) — never hollow placeholder shells that only dare to print the company name.
  - If the entity operates across multiple distinct contexts (e.g. formal institutional/partner settings *and* expressive public/product touchpoints), explicitly define **what stays invariant** vs **how the visual register flexes**.

---

## 3. Placing the Generative ↔ Deterministic Handoff Boundary

`generate-image` provides two complementary substrates — **neither is a style**, and each has a distinct cognitive ceiling:

- **Generative Exploration & Materiality (`kind: generate`, `grid: 2x3` / `3x3`):**
  - Excels at unbounded sculptural/typographic ideation, bespoke handcrafted lettering, illustration, procedural light/optical studies, photography, tactile surfaces, and spatial staging.
  - **Key discipline:** Never cripple creative imagination by hand-coding primitive geometric shapes (`<rect>`) as a signature emblem, or passing off unmodified OS system fonts as a bespoke brand logotype. Explore broadly first, cull ruthlessly, then lock an **opaque canonical master** (never feed transparent RGBA PNGs as upstream `--ref`!).
- **Deterministic Preservation & Assembly (`trace_svg: true`, `kind: render`, `kind: stitch`):**
  - **`trace_svg: true`:** Vectorizes crisp flat generative marks and custom logotypes into smooth multi-color Bezier `.svg` production files (`potrace` / `vtracer`).
  - **`kind: render` (HTML/SVG → high-DPI PNG / PDF, ¥0):** Guarantees exact repeatable typography, authentic dense copy/product UI/technical diagrams, print-ready production spec sheets (color codes, clearspace, minimum sizes, misuse rules), and multi-page PDF handoff.
  - **Flat-First Staging Pattern:** When photographic realism is needed for typography-heavy physical or screen artifacts, render the finished flat artwork deterministically first (`kind: render`), then pass it as `--ref` into `kind: generate` (`background: opaque`) to stage tactile light and materiality without font drift.
  - **`kind: stitch` (¥0):** Assembles modular reviewed sections into a seamless narrative showcase (long scroll or multi-spread presentation) whose visual cadence matches *this* brand's own temperament — never a one-size-fits-all template.

---

## 4. Critical Self-Audit (Before Anything Reaches the User)

Audit at full resolution across two strictly separate layers:

- **Layer A · Technical Hygiene (Baseline, 0 → 60):**
  - Stroke-for-stroke fidelity to opaque anchors; zero font drift; zero garbled characters; true opaque RGB for photographic scenes (`background: opaque`) and clean alpha for leaf transparent assets; genuine `.svg`/`.pdf` production artifacts where promised.
- **Layer B · Design Craft & Conviction (Deliverable Bar, 60 → 100):**
  - **Authenticity:** Does every visual decision feel inevitably born from *this* subject — with zero transplanted tropes from unrelated sectors or few-shot examples?
  - **Distinctiveness:** Does the core visual idea survive stripping away all explanatory text?
  - **Tension & Polish:** Does the composition exhibit deliberate scale contrast, breathing rhythm, and authentic material/digital craft (zero sterile uniform-box PPT feel)?
  - **Adversarial Doubt:** Actively articulate the **sharpest criticism a harsh creative director would level right now**. If that criticism holds water, fix the root cause and iterate before delivering.
