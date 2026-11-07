# Map slot (for P4)

The operator screen's **Houses** tab shows the house list on the left and a map slot on the right. The slot shows a placeholder until a map module is installed. P4 delivers that module. Nothing else in the screen has to change.

## What P4 adds

| File | Served at | Purpose |
|---|---|---|
| `src/ui/static/map/map.js` | `/static/map/map.js` | The map module. Loaded automatically on page load; a 404 is ignored. |
| `<ARTIFACT_URI>/geo/station.geojson` | `/geo/station` | Geometry of the neighbourhood (optional). Download OpenStreetMap data once, do not call Overpass from the browser. |

Libraries (for example Leaflet) and tiles are P4's choice. Keep every file under `static/map/`, which is mounted at `/static/map/`. Add a file pattern to `[tool.setuptools.package-data]` in `pyproject.toml` if a new extension is needed.

## The module contract

`map.js` registers one global before the page finishes loading:

```js
window.StationMap = {
  // Called once, the first time the Houses tab is visible. `el` is an empty box that fills the slot (440 px high).
  // host.geo    the parsed GeoJSON from /geo/station, or null when there is none
  // host.select(houseId | null)  tell the screen a house was picked on the map
  mount(el, host) {},

  // Called on every change of interval, plan, selection or kill switch. Must be cheap and idempotent.
  update(view) {},

  onShow() {},   // optional: the Houses tab became visible again (for example Leaflet's invalidateSize)
  destroy() {}   // optional
};
```

`view` is built by the screen from the agent API; the map never calls the API itself:

```js
{
  pt_id: "PT-A",
  interval_start: "2025-06-21T10:00:00Z",   // UTC, null when no day is picked
  selected: "H06" | null,                    // house picked in the list or on the map
  kill_switch: false,
  houses: [
    {
      id: "H06",
      kwp: 25.0,
      contract_cap_kw: 9.0 | null,
      limit_kw: 9.0 | null,                  // null: no plan for this interval
      share: 0.36 | null,                    // limit_kw / kwp
      status: "ok" | "review" | "blocked" | "none",
      capped: true
    }
  ]
}
```

## Status colours and symbols (use the same everywhere)

| `status` | Meaning | Colour | Symbol |
|---|---|---|---|
| `ok` | model limit, guard passed | `#1c7a5a` | ✓ |
| `review` | fixed limit (case sent to a human) or contract cap | `#ffd978`, dark text | ! |
| `blocked` | blocked by the guard | `#b3261e` | × |
| `none` | no plan | `#e9eef1` | none |

Colour is never the only signal: always add the symbol or the text. Markers need a hit area of at least 44 px.

## Geometry (`/geo/station`)

A GeoJSON `FeatureCollection` in WGS84. Properties the screen understands:

- `kind: "house"` with `house_id` equal to a `house_id` of `GET /station`. Point or building polygon.
- `kind: "transformer"` with `pt_id`.
- `kind: "feeder"` (LineString), optional `name`.

Houses in the station without a geometry must still be reachable from the list below the map. The screen already shows a labelled house list in the schematic; P4 decides whether the map shows an "unplaced houses" note.

## Rules

- The grid behind the map is synthetic. The screen prints "Illustrative layout. The grid behind this map is synthetic" under the map; keep the OpenStreetMap attribution visible inside the map.
- The map shows only what `view` gives it. It does not compute limits, statuses or loads.
- A map error must not break the screen: the screen catches exceptions from `mount` and `update` and shows a message, but a module that throws on every update is still a broken demo, so test it with the kill switch on and with no plan.
- Respect `prefers-color-scheme` or keep a neutral light basemap that reads well inside both themes.
- Send a `User-Agent` header when downloading from Overpass, and commit no raw data (see `.gitignore`).

## Try the contract without P4

Save this as `src/ui/static/map/map.js`, reload the screen (do not commit it):

```js
window.StationMap = {
  mount(el, host) { this.el = el; this.host = host; },
  update(view) {
    this.el.replaceChildren(...view.houses.map(h => {
      const b = document.createElement("button");
      b.textContent = h.id + " " + h.status;
      b.onclick = () => this.host.select(h.id);
      return b;
    }));
  }
};
```
