# Neighbourhood map (P4)

The operator screen's **Houses** tab shows a map on the left and the houses, grouped by neighbourhood, on the right. `map.js` in this folder is the map module. It is a small slippy map with no library: OpenStreetMap tiles as images, outlines and feeders as SVG, houses and neighbourhoods as buttons. Without a network the tiles stay empty and everything else still works.

Zoomed out it shows one bubble per neighbourhood (name, number of houses, worst status). From zoom 12 it shows the houses, coloured by the plan's status, and the feeder of each neighbourhood. The chips at the top, the bubbles and the neighbourhood rows in the list all zoom to a neighbourhood; clicking a house on the map selects it in the list and the other way round.

## Run the three-neighbourhood demo

The coordinates come from a customer table (`Customer, Generator Capacity, Postcode, lat, lon, localities`). Keep it out of git (`data/` is ignored).

```sh
python -m src.ui.geo_build --customers data/p4/customers.csv --out artifacts
STATION_FILE=artifacts/station/demo_station.json ARTIFACT_URI=artifacts python -m uvicorn src.grid.demo_api:app --port 8000
API_URL=http://127.0.0.1:8000 ARTIFACT_URI=artifacts python -m uvicorn src.ui.app:app --port 8001
```

`geo_build` writes `artifacts/geo/station.geojson` (the screen serves it at `/geo/station`) and `artifacts/station/demo_station.json` (the station for the agent API). It chooses the three neighbourhoods itself: three groups of nearby postcodes (`--radius-km`, default 4) with enough customers each (`--houses-per-neighbourhood`, default 15), as close together as possible. With the table of 300 customers this gives Normanhurst, Allambie and Balgowlah in northern Sydney, 15 houses each. Names come from the first locality of the biggest postcode of a group.

What the data is and is not:

- The coordinates are **postcode centroids**, not addresses. Every house gets a deterministic offset around its centroid (a spiral of 120 to about 500 m), so houses do not sit on top of each other. Rerunning gives the same positions.
- The three neighbourhoods are the **three feeders** of the twin. The station lists houses neighbourhood by neighbourhood and passes `houses_per_neighborhood` to the twin, so house `i` is on feeder `i // 15` exactly as `build_grid` assigns it (tested). Five houses form a node.
- **Positions never enter the physics.** The twin's line lengths are assumed values, not distances on the map, and one transformer serves all three neighbourhoods although they are kilometres apart. The screen says so under the map.
- Generator capacity is the house's kWp. No contract caps are set, because the table has none.

## The module contract

`map.js` registers one global before the page finishes loading. To replace it, keep this interface:

```js
window.StationMap = {
  // Called once, the first time the Houses tab is visible. `el` is an empty box that fills the slot.
  // host.geo    the parsed GeoJSON from /geo/station, or null when there is none
  // host.select(houseId | null)  tell the screen a house was picked on the map
  mount(el, host) {},

  // Called on every change of interval, plan, selection or kill switch. Must be cheap and idempotent.
  update(view) {},

  focus(groupId | null) {},  // optional: zoom to a neighbourhood, or to all of them
  onShow() {},               // optional: the Houses tab became visible again
  destroy() {}               // optional
};
```

`view` is built by the screen from the agent API; the map never calls the API itself:

```js
{
  pt_id: "PT-A",
  interval_start: "2025-06-21T10:00:00Z",   // UTC, null when no day is picked
  selected: "109" | null,                    // house picked in the list or on the map
  kill_switch: false,
  groups: [{id: "N1", name: "Normanhurst"}],
  words: {ok: "..."},                       // optional: wording per status, for tooltips and labels
  houses: [
    {
      id: "109",
      group: "N3" | null,                    // neighbourhood id from the geometry
      kwp: 6.2,
      contract_cap_kw: 9.0 | null,
      limit_kw: 2.17 | null,                 // null: no plan for this interval
      share: 0.35 | null,                    // limit_kw / kwp
      status: "ok" | "review" | "blocked" | "none",
      capped: false
    }
  ]
}
```

## Status colours and symbols (use the same everywhere)

| `status` | Meaning | Colour | Symbol |
|---|---|---|---|
| `ok` | model limit, guard passed | `#2f7d5b` | ✓ |
| `review` | fixed limit (case sent to a human) or contract cap | `#ffd978`, dark text | ! |
| `blocked` | blocked by the guard | `#b3261e` | × |
| `none` | no plan | `#e9eef1` | none |

Colour is never the only signal: always add the symbol or the text. The module reads the page's CSS variables (`--ok`, `--rev`, `--bad`, `--ink`, `--bg`, `--line2`, `--soft`), so light and dark themes both work.

## Geometry (`/geo/station`)

A GeoJSON `FeatureCollection` in WGS84, with `meta.provenance: "assumed"`. Properties the screen and the module understand:

- `kind: "neighbourhood"` (Polygon) with `id` and `name`: the outline, one per feeder.
- `kind: "house"` (Point) with `house_id` equal to a `house_id` of `GET /station`, `neighbourhood` (an `id` above) and `node`.
- `kind: "feeder"` (LineString) with `neighbourhood`: the path through the nodes of a neighbourhood.

Houses of the station without geometry are still listed on the right; with no geometry at all the list is flat and the module shows how to build it.

## Rules

- The grid behind the map is synthetic. The screen prints that under the map; keep the OpenStreetMap attribution visible inside the map.
- The map shows only what `view` gives it. It does not compute limits, statuses or loads.
- A module error must not break the screen: the screen catches exceptions from `mount`, `update` and `focus`. Still, test with the kill switch on and with no plan.
- Do not call Overpass or any API from the browser; build data files offline. Tiles from `tile.openstreetmap.org` are for light, demo use; switch to a tile provider before any real load.
