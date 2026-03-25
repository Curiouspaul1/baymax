# Design System Document

## 1. Overview & Creative North Star
**Creative North Star: The Industrial Curator**

This design system is engineered for the high-stakes environment of artisan vetting. While the core of the application is a "utilitarian" admin dashboard, we reject the notion that utility must be synonymous with the generic. The "Industrial Curator" aesthetic blends the raw, high-contrast energy of a workshop with the sophisticated editorial precision of a premium gallery. 

We move beyond the standard grid through **intentional asymmetry** and **tonal depth**. Large, bold typography scales are used to create a sense of authority, while the layout utilizes overlapping "sheets" of data to simulate a physical vetting desk. This isn't just a dashboard; it’s a high-end tool for discerning professionals.

## 2. Colors
Our palette is rooted in the high-visibility yellow and deep charcoal of the brand, but expanded into a nuanced range of functional tiers.

### The Palette
*   **Primary (`#745b00`):** Used for critical actions and brand presence.
*   **Primary Container (`#ffcc00`):** Our signature vibrant yellow, used for primary highlights and status backgrounds.
*   **Secondary (`#5d5e61`):** A sophisticated charcoal that provides the "Industrial" anchor to the "Curator" aesthetic.
*   **Surface Tiers:** Ranging from `surface-container-lowest` (`#ffffff`) to `surface-container-highest` (`#e2e2e2`).

### Color Rules
*   **The "No-Line" Rule:** 1px solid borders are strictly prohibited for sectioning. We define boundaries through background color shifts. A `surface-container-low` data panel should sit on a `surface` background to create a "ghosted" edge.
*   **Surface Hierarchy & Nesting:** Treat the UI as physical layers. Use `surface-container-lowest` for cards containing dense artisan data to make them "pop" against a `surface-container-low` dashboard background. 
*   **The "Glass & Gradient" Rule:** For floating headers or sidebars, use Glassmorphism. Apply a `surface` color at 80% opacity with a `backdrop-blur-md` effect.
*   **Signature Textures:** Use subtle linear gradients on primary buttons (transitioning from `primary` to `primary_fixed_dim`) to add tactile depth that flat color cannot provide.

## 3. Typography
We utilize **Inter** as our foundational typeface. Its geometric clarity ensures that even the densest artisan data remains legible under scrutiny.

*   **Display Scale:** Large, high-impact `display-lg` (3.5rem) settings are reserved for dashboard overviews, creating a bold, editorial entrance to the data.
*   **Headline & Title:** These are the "anchors." Use `headline-sm` for section headers (e.g., "Guarantor Security Vetting"). They provide the authoritative structure.
*   **Body & Labels:** `body-md` is the workhorse for data entry, while `label-sm` (uppercase) is used for input field descriptors to mimic the look of industrial forms.

The hierarchy is intentionally extreme. We pair large headlines with significantly smaller, high-contrast labels to create a sophisticated, curated feel.

## 4. Elevation & Depth
In this system, depth is a function of light and tone, not lines.

*   **The Layering Principle:** Depth is achieved by "stacking" surface tiers. To separate the vetting checklist from the artisan profile, place the checklist on a `surface-container-high` background to give it immediate visual priority.
*   **Ambient Shadows:** Use shadows sparingly. When a card must float, use a blur value of `24px` or higher with an opacity of `4%` using a tinted `on-surface` color. It should feel like a soft glow of light, not a drop shadow.
*   **The "Ghost Border" Fallback:** If accessibility requires a container edge, use the `outline-variant` token at 15% opacity. This provides a "suggestion" of a border without breaking the editorial flow.
*   **Glassmorphism:** Use semi-transparent layers for the Artisan Sidebar. This allows the primary dashboard content to bleed through slightly, maintaining the user's context even when focused on a specific detail.

## 5. Components

### Buttons
*   **Primary:** Solid `primary_container` background with `on_primary_container` text. For "Complete Enrollment" actions, use a subtle 5% black-to-transparent gradient to give it a "pressed" industrial feel.
*   **Secondary:** Ghost style. No background, `outline` token at 20% opacity for the border.

### Artisan Vetting Cards
*   **Layout:** Forbid divider lines. Use `spacing-8` (1.75rem) to separate "Personal Details" from "Professional Profile."
*   **Visual Shift:** Use a `surface-container-low` background for the card body to distinguish it from the `surface` of the page.

### Input Fields
*   **Style:** Soft-rounded (`md` - 0.375rem). Use `surface-container-highest` for the background. 
*   **States:** On focus, the background shifts to `surface-container-lowest` with a 2px `primary` bottom-border only (no full-box stroke).

### Chips & Status Indicators
*   **Vetting Status:** Use the `tertiary` (deep red) for "Rejected" and `primary` (yellow) for "Pending." Status indicators should be pill-shaped (`rounded-full`) but with low-saturation backgrounds to maintain a professional, rather than "bubbly," aesthetic.

### Additional Components: The "Timeline Ledger"
*   For artisan history, use a vertical timeline that utilizes the "No-Line" rule. Use background color blocks of `surface-container-low` to group time-based events rather than a vertical line connecting dots.

## 6. Do's and Don'ts

### Do
*   **Do** use asymmetrical spacing. A wider left margin for the sidebar creates a more custom, editorial feel.
*   **Do** use `surface-container` shifts for data tables. Alternate row colors using `surface` and `surface-container-low`.
*   **Do** utilize the brand's sharp icon style for status cues (e.g., the faceted location pin).

### Don'ts
*   **Don't** use 100% black. Use the `secondary` charcoal (`#5d5e61`) for text to avoid harsh, "un-designed" contrast.
*   **Don't** use standard Tailwind `border-gray-200` for everything. If you need a divider, use a `1.5` spacing gap or a tonal shift.
*   **Don't** crowd the data. Artisan vetting requires focus; use the `spacing-10` and `spacing-12` tokens to give sections room to breathe.