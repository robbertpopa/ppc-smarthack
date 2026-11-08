# Presentation deck sources

The slide deck for the PPC Smarthack presentation, in two languages:

| Folder | Language | Slides |
|---|---|---|
| `en/` | English | 16 |
| `ro/` | Romanian | 16 |

Each folder has `deck.json` (slide order, sections, typeface) and one HTML file per slide in `slides/`. The slides use a closed HTML subset on a fixed 1920×1080 canvas; the speaker notes are in the `<aside>` at the end of each slide. The outline follows [../slides.md](../slides.md) and the demo follows [../demo-script.md](../demo-script.md).

## Before presenting

- Slide 14 ("Results") shows the **exploration** figures from [docs/04](../../docs/04-chosen-idea.md), not the output of the evaluation. Replace them with `eval/<run-id>/summary.json` after `python -m src.eval.run`, and do not show the slide if that file says `mock: true`.
- Slide 4 is an illustration with an invented shape of the day. It carries no measured number and says so on the slide.
