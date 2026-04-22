# Design System Strategy: Clinical Intelligence & The Editorial Lab

## 1. Overview & Creative North Star
The Creative North Star for this system is **"The Clinical Curator."** 

In medical research, density often leads to cognitive fatigue. This system rejects the "dashboard-of-widgets" cliché in favor of a high-end editorial layout. We treat medical data not as raw output, but as a published manuscript. By utilizing intentional asymmetry—placing heavy research text against expansive white space—we create a "breathing" interface that feels both authoritative and calm. We break the rigid grid by allowing the AI chat interface to feel like a floating, glass-like layer over a solid bedrock of research documentation.

## 2. Color Theory: Tonal Precision
The palette transitions from sterile whites to deep, intellectual teals. We avoid pure blacks to maintain a sophisticated, low-strain reading environment.

*   **Primary Hierarchy:** Use `primary` (#005050) for core intellectual actions and `primary_container` (#006a6a) for active research states.
*   **The "No-Line" Rule:** Direct sectioning with 1px borders is strictly prohibited. To separate the sidebar from the chat or the chat from the research cards, use background shifts. Place a `surface_container_low` (#f3f4f3) sidebar against a `surface` (#f9f9f9) main stage.
*   **Surface Hierarchy & Nesting:** Create depth through "Physical Stacking."
    *   *Base Layer:* `surface` (#f9f9f9)
    *   *Sectional Layer:* `surface_container` (#edeeee)
    *   *Interactive Card:* `surface_container_lowest` (#ffffff)
*   **The "Glass & Gradient" Rule:** Floating AI elements should utilize `surface_container_low` at 80% opacity with a `20px` backdrop-blur. For primary action buttons, use a subtle linear gradient from `primary` (#005050) to `primary_container` (#006a6a) at a 135-degree angle to provide a "gemstone" depth.

## 3. Typography: The Authority of Sans
We employ a dual-typeface system to balance modern AI fluidity with clinical rigor.

*   **Display & Headlines:** **Manrope** is used for `display-lg` through `headline-sm`. Its geometric yet friendly terminals provide a "Modern Lab" feel. Use `headline-md` (1.75rem) for research paper titles to ensure they feel like headlines in a premium journal.
*   **Body & Data:** **Inter** is our workhorse. Use `body-md` (0.875rem) for chat bubbles and research summaries. Inter’s high x-height ensures medical terminology (e.g., "Oligonucleotide") remains legible at smaller scales.
*   **Functional Labels:** `label-sm` (0.6875rem) in `on_surface_variant` (#3e4948) should be used for metadata like "DOI Number" or "Confidence Score," set in All Caps with a 0.05em letter spacing for an architectural aesthetic.

## 4. Elevation & Depth: Tonal Layering
Traditional drop shadows are too "software-generic." We use light and tone to define space.

*   **The Layering Principle:** Instead of shadows, an "Inset Research Card" should be `surface_container_highest` (#e2e3e2) nested within a `surface_container_low` (#f3f4f3) wrapper.
*   **Ambient Shadows:** For "Active" floating elements (like an AI suggestion popover), use an ultra-diffused shadow: `0px 12px 32px rgba(0, 80, 80, 0.06)`. Note the tint—the shadow uses a hint of the `primary` color rather than grey.
*   **The "Ghost Border" Fallback:** If high-density data requires containment, use `outline_variant` (#bec9c8) at 15% opacity. It should be felt, not seen.
*   **Glassmorphism:** The AI input bar should be a "Floating Vessel." Use `surface_container_lowest` (#ffffff) with 70% opacity and a `12px` blur, sitting 24px (Spacing `6`) from the bottom of the viewport.

## 5. Components & Primitive Styling

*   **Buttons:**
    *   *Primary:* `primary` background, `on_primary` text. `xl` (0.75rem) roundedness. No border.
    *   *Secondary:* `secondary_container` background. No border. Soft transitions.
*   **Research Cards:** Forbid dividers. Use `Spacing 5` (1.25rem) of internal padding. Title uses `title-md`, body uses `body-sm`. Group related metadata using background shifts, not lines.
*   **RAG Status Indicators:** For "Ingesting Data," do not use a standard spinner. Use a subtle pulse animation on a `tertiary` (#00497d) chip with 10% opacity.
*   **Chat Interface:**
    *   *User Bubbles:* `surface_container_high` (#e7e8e8) with `lg` (0.5rem) roundedness.
    *   *AI Bubbles:* Transparent background with a "Ghost Border" and `body-md` typography.
*   **Input Fields:** Use `surface_container_low` (#f3f4f3) for the field background. On focus, transition the background to `surface_container_lowest` (#ffffff) and apply a 1px "Ghost Border" using `primary`.

## 6. Do’s and Don'ts

### Do:
*   **Do** use asymmetrical margins. If the research text is centered, keep the AI chat tools offset to the right to create an editorial "marginalia" feel.
*   **Do** use `Spacing 8` (2rem) and `12` (3rem) for vertical separation between major research blocks.
*   **Do** use `primary_fixed_dim` (#84d4d3) for highlighting specific medical entities within text strings.

### Don’t:
*   **Don’t** use 100% opaque black (#000000). Use `on_surface` (#1a1c1c) for all primary text.
*   **Don’t** use standard `1px` dividers. If you feel the need to separate, use a `1px` height `surface_variant` (#e2e3e2) box with 40% opacity.
*   **Don’t** use sharp corners. Everything must have at least `DEFAULT` (0.25rem) roundedness to maintain the "Clinical Curator" softness.