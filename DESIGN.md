# Design

Scope: the meter web app in `server/frontend/src` (device list and device page). Mode: Operate.
Direction: Printed plate (lexicon-shoulder-and-plate, adapted). Source of truth for tokens: `.impeccable/design.json`.

## Color strategy

Restrained. Warm paper ground and engraving-black ink carry the page. Color appears only inside framed plates: ultramarine ink for the chart, and a vermilion hairline box for the reset note. No cards, no colored fields, no shadows.

## Tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `--paper` | `#e9eee6` | `#141a17` | page ground |
| `--plate-bg` | `#f6f8f3` | `#1b231f` | inside framed plates |
| `--ink` | `#1b2320` | `#e6ede7` | text, rules, borders |
| `--ink-soft` | `#56615b` | `#9fb0a4` | secondary text, axis labels |
| `--rule` | `#bfc9bf` | `#33403a` | hairlines, grid |
| `--plate-ink` | `#2c3e8f` | `#8fa2ff` | chart bars |
| `--vermilion` | `#b8402a` | `#ef7a5e` | reset note border |
| `--online` | `#2f6b3a` | `#8fd19e` | online status |
| `--warn-bg` / `--warn-text` | `#f7e3d5` / `#7a2612` | `#3a2519` / `#f2b49c` | reset note |
| `--error-text` | `#8a2118` | `#f2a79c` | load error |

Radius: none. Borders are 1px ink. Double rules (3px) mark the page head.

## Typography

Literata (serif), loaded from Google Fonts, weights 400 to 700. Every number uses lining, tabular figures.

- Plate total: `clamp(3.25rem, 17vw, 5rem)`, weight 700, tracking -0.03em.
- Page title: 1.25rem, weight 700.
- Entry term: 1.125rem, weight 700. Entry definition: 0.9375rem, `--ink-soft`.
- Period index: 0.9375rem, weight 500; selected item weight 700 with a 3px ink underline.

## Components

- **Head**: sticky, paper ground, 3px double rule underneath. Device name left, status mark right.
- **Entry (device row)**: ruled list. Term in bold, definition below, chevron in ink.
- **Status mark**: filled dot for online, hollow for offline, always with its word. In the list the word is hidden, and it stays available to screen readers.
- **Plate**: 1px ink border with an outer 1px outline offset 4px. Holds the total and the chart.
- **Period index**: text tabs with a selected underline. Scrolls sideways on narrow screens.
- **Window nav**: printed arrows around the window label. Disabled arrows drop to the rule color.
- **Chart**: Chart.js bars in `--plate-ink`, square ends, ink baseline, hairline grid.

## Motion

None beyond the skeleton pulse, which stops under `prefers-reduced-motion`. No entrance motion.

## Accessibility

Focus is a 2px ink outline. Tap targets at least 44px. Status is never color alone. Body text meets AA on the paper ground in both themes.
