# PPC-style UI redesign

## Goal
Re-skin both UI pages (`src/ui/static/index.html`, `src/ui/static/simulation.html`) to match the PPC Group visual identity (ppcgroup.com). Behaviour, data flow and the map are unchanged. Light theme only; the current `prefers-color-scheme: dark` block is removed.

## Approach
One shared stylesheet, `src/ui/static/theme.css`, holds tokens and base components. Both pages link it and drop their inline duplicates. `src/ui/app.py` gets a `/static/theme.css` route or mount, next to the existing `/static/map` mount.

## Tokens (taken from ppcgroup.com CSS variables)
| Token | Value | Use |
|---|---|---|
| `--ink` | `#000f1e` | text, header and hero surfaces |
| `--bg` | `#ffffff` | page background |
| `--soft` | `#f2f2f2` | cards, hover, table stripes |
| `--muted` | `#67757c` | secondary text |
| `--line` / `--line2` | `#dddfe0` / `#c5c9cc` | borders |
| `--brand` | `#00a3e0` | primary button fill, focus ring, chart accents |
| `--brand-text` | darker blue (about `#0064B4`) | links and text-sized blue (cyan on white is about 2.9:1) |
| `--ok` | `#0F872D` | OK status |
| `--rev` | `#F06E00` | review status (replaces amber) |
| `--bad` | `#fa4616` | blocked / error / kill |
| `--band` | `#a2d3f3` | info band |

Font stack: `"Open Sans", system-ui, -apple-system, "Segoe UI", sans-serif` with tabular numbers. PingLCG is licensed, so it is not used.

## Components
- **Header:** navy bar, text wordmark in a PPC-like style (no copied logo asset), "Simulated data" tag kept.
- **Buttons:** 4px radius, bold 14px, padding 12px 24px. Primary = cyan fill with navy text; secondary = outlined; destructive = outlined in `--bad`.
- **Hero verdict block (operator screen):** navy surface, white text.
- **Tabs, rows, chips, day-strip dots, tags:** recolored with the tokens; structure unchanged.
- **simulation.html:** same header and theme; panels become bordered cards on `--soft`. Its Romanian copy is unchanged.

## Out of scope
Behaviour, API calls, the map, PPC logo or imagery, dark mode.

## Verification
Run the app, screenshot both pages, and check body-text and status contrast (target WCAG AA, 4.5:1). Confirm no remaining references to the old palette (`#fbfbf9`, `#17191c`, `#c98600`) and no `prefers-color-scheme` rules.

## Notes
The current branch (`docs/dynamic-buyback-pricing-design`) is for the pricing docs; implementation should go on its own branch.
