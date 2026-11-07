# P4: neighbourhood map for the operator screen

**Owns:** `src/ui/map/` (data builder), `src/ui/static/map.js`, `src/ui/static/map.css`, `src/ui/static/map_data.geojson`, `tests/test_ui_map.py`. **Touches only by agreement with P3** (two small edits, listed in step 3): `src/ui/app.py` and `src/ui/static/index.html`.

Read first: [../08-parallel-plan.md](../08-parallel-plan.md), [../09-contract.md](../09-contract.md), [p3-grid-ui.md](p3-grid-ui.md) (the screen this plugs into), [../11-commit-plan.md](../11-commit-plan.md) (commit rules; no trailers).

## Goal
Give the operator screen a map of a real Bucharest neighbourhood: the houses of the station drawn on real building outlines from OpenStreetMap, coloured by the plan status, with the transformer in the middle. It makes the dashboard readable at a glance. This is the optional map from P3's Phase 3 moved into its own role, so it can start now and does not wait for P2.

It has **no dependency on the model**: it reads the same agent API as the screen (`/station`, `/plan`, `/grid_state`), which already works on mock forecasts. When the real model lands the map just shows real limits.

## What the jury sees
- A map card on the operator screen, next to the plan: building outlines, one marker per house, the transformer station.
- House colours follow the plan exactly as the house cards do: green (model limit, guard passed), yellow (fixed fallback or contract cap), red (blocked by the guard), grey (no plan).
- The transformer marker shows its loading; the house at `v_max_node` (if it maps to a house) has a ring.
- Click a house: limit in kW, share of its kWp, cap if any.
- Moving the time slider or approving a plan updates the map, because it is drawn from the same data.
- A fixed banner on the map: "Illustrative layout. Buildings are real (OpenStreetMap), the grid and the house-to-building assignment are synthetic."

## What you deliver
| Step | Branch | Deliverable |
|---|---|---|
| 1 | `ui/map-data` | Script that downloads building outlines once and writes a small GeoJSON; deterministic house-to-building assignment; tests |
| 2 | `ui/map-view` | Standalone page `/map` drawing the map from the GeoJSON and the live API (SVG, no tiles) |
| 3 | `ui/map-wire` | The map card inside the dashboard, driven by the screen's own refresh |

## Tasks

### Step 1: data (`ui/map-data`)
- Pick one residential neighbourhood in Bucharest with enough separate houses (a few hundred metres across; the team picks, see "Decisions"). Record the bounding box in the script.
- `python -m src.ui.map.build_data` queries Overpass for `building` ways inside the box, **once**, sends a `User-Agent` header that names the project (no personal e-mail), and writes `src/ui/static/map_data.geojson`: building polygons plus one point for the transformer station. Keep it small (under about 300 KB: drop tags, round coordinates to 6 decimals, keep only buildings that look like houses).
- Commit the GeoJSON: the demo must run offline. Put the source and licence in the script docstring and on screen: "© OpenStreetMap contributors, ODbL". The download script is committed too, so the file can be regenerated.
- `assign(houses, buildings, seed=0) -> dict[house_id, building_id]`: deterministic, one building per house, nearest buildings to the transformer first. It must work for any number of houses `/station` returns (8 in the mock, more in the twin). If there are fewer buildings than houses, fail with a clear message.
- Feeders are drawn as straight lines from the transformer to each house (synthetic). Do not claim they are cables.

### Step 2: the view (`ui/map-view`)
- Draw with plain SVG from the GeoJSON, with a simple equirectangular projection fitted to the box. **No map tiles, no Leaflet:** no internet needed on stage, no tile-usage policy, no extra dependency. (If time remains, a tile layer is an optional extra, off by default.)
- One function the dashboard calls: `window.ppcMap.update({station, plan, gridState})`. It must tolerate `plan` and `gridState` being null (grey houses) and a `station` that changed.
- Colour rules are the same as in `renderPlan` in `index.html` (blocked, abstain or capped, ok, no plan). Do not invent a second rule: copy the logic into one small function and test it, or ask P3 to export it.
- Reuse the CSS variables of the screen (`--ok`, `--warn`, `--bad`, `--muted`). Add a legend and the banner above.
- Accessible: each house marker has a text label (`house_id`) and the card shows the same numbers as text, not colour only.
- Standalone `/map` page that fetches `/api/station`, `/api/plans` and `/api/grid_state` itself, so it can be demoed before the wiring.

### Step 3: wiring (`ui/map-wire`, agree with P3 first)
Two small edits in P3's files. Post them in the group, get a "yes", and ask P3 to review the PR.
1. `src/ui/app.py`: serve the two new static files and the GeoJSON (the app only serves `/` and `/simulation` today), and the `/map` page. Add nothing to the proxy allow-list: the map only reads endpoints that are already allowed.
2. `src/ui/static/index.html`: add one `<section class="card">` with the map container, load `map.js` and `map.css`, and call `window.ppcMap?.update(...)` at the end of `renderPlan` and `loadGrid`. If `map.js` fails to load the dashboard must still work.

## Interfaces
- **You consume:** the agent API (`station`, `plan`, `grid_state`), already live on mocks; the contract in [../09-contract.md](../09-contract.md).
- **You provide:** `window.ppcMap.update(...)`, the GeoJSON and the `/map` page to P3 (screen) and P1 (demo flow).
- **You do not change** the contract, the API or anything in `src/agent/`, `src/grid/`, `src/ml/`. If you need a field the API does not return (for example a per-house voltage), ask P1; do not fake it.

## Tests (`tests/test_ui_map.py`)
1. The builder is deterministic: same box and seed, same assignment.
2. Every house of the mock station gets exactly one building, and no building is used twice.
3. Fewer buildings than houses fails with a clear message (no silent reuse).
4. The GeoJSON is valid, polygons are closed, coordinates fall inside the box, file size under the limit.
5. The colour function gives green, yellow, red and grey for the four cases (model plan, abstain or cap, guard blocked, no plan).
6. `GET /map` and the map assets are served; the proxy allow-list did not grow.

The builder's network call is never run in tests: use a tiny in-test Overpass response.

## Definition of done
- The map card is on the operator screen, and moving the slider or acting on a plan changes the map.
- It works with no internet and with the mock API.
- The simulated-layout banner and the OpenStreetMap attribution are visible.
- `make test lint smoke` pass, no secrets, no downloads at runtime.

## Pitfalls
- Overpass is a shared public service: query once, cache the result in the repository, send a `User-Agent`, never call it from the demo.
- A real neighbourhood next to a German-style grid and Australian profiles is easy to over-read. Say on screen that the layout is illustrative.
- Do not place houses by real addresses or name real people or streets in the repository.
- Colour is not the only signal (accessibility, projector): keep the text labels.
- The station may have more houses than the mock; do not hard-code 8.

## Decisions the team still has to confirm
- **Which neighbourhood** (needs a clear grid of detached houses; one that is not sensitive to show).
- **Commit the GeoJSON or not.** Proposed: yes, small and with attribution, so the demo is offline.
- **Tiles or no tiles.** Proposed: no tiles by default.

## If you fall behind
Keep: the static map with coloured houses and the transformer, wired to the dashboard. Cut first: popups, the `v_max_node` ring, feeder lines, the standalone page.
