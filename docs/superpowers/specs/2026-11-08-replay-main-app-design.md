# Replay main app: the last two months, before and after the dynamic limit

Status: draft for review, 2026-11-08. Nothing here is built yet.

## Goal
The main page of the app shows a replay of the demo period (2013-05-01 to 2013-06-30, Sydney dates) for the
210-house station, by day and by half hour, on the existing map. Two views over the same clock:

* **Before**: the fixed limit (`StationConfig.static_share`, 36% of kWp for every house).
* **After**: our dynamic limit (`safe-cap-qgb-v2-dataset`: q05 minus the online offset, fixed limit when the
  model abstains).

The story it must show: with the fixed limit, houses are either capped below what the grid could take (lost
sales) or the station is pushed past what the transformer can carry; with our limit, sales go up and the
transformer limit is not crossed.

## Decisions taken with the user
* Main page, only the simulation. The old operator screen moves to `/operator` and is not deleted.
* Precomputed replay with a play clock, not a model call per request.
* Visualisation is the existing map module (`src/ui/static/map/map.js`), not a new map.
* Houses: the 210 station houses only (the ones with power-flow truth). The other 90 dataset houses are left
  off and the page says so.

## Data (offline build)
`python -m src.ui.replay_build` writes `<ARTIFACT_URI>/replay/index.json` and `replay/days/<YYYY-MM-DD>.json`.

1. Generate the demo-period labels with `src.grid.labels --final-eval` for 2013-05-01 + 61 days (all 61 days
   have complete rows for the 210 houses; checked 2026-11-08). This is the power-flow truth `safe_share`.
2. Load the model with `model_io.load("safe-cap-qgb-v2-dataset", "PT-A")`. Build features from the labels
   (`train.training_rows`), predict the quantiles, replay the online offset from the stored `c_start`, apply the
   abstention rule. This is the same logic as `src/eval/score_dataset.py`; the builder reuses it, no second copy.
3. Per daylight half hour: `safe_share` (truth), `fixed_share` (0.36), `model_share`, `abstained`.
4. Per house and half hour, from `demo.parquet` surplus (`pv_scale * gg - (gc + cl)`, clipped at 0, the same
   formula as `surplus_kw`), for each policy: exported kW `min(surplus, share * kwp)` and curtailed kW
   `surplus - exported`.
5. Status per house, per policy:
   * **red**: the policy's share is above `safe_share` (the same test as the violation rate in
     `src.eval.metrics.evaluate`), so the station is over what the grid can carry in that interval;
   * **amber**: not red, and the house is curtailed (surplus above its cap);
   * **green**: not red, not curtailed;
   * **grey**: no reading or no surplus.
6. Summary: per day and for the 61 days, intervals in violation and exported kWh, for both policies.

Size: about 28 daylight intervals x 210 houses x 2 policies per day. One JSON per day keeps each request small.

## App
* `GET /` serves the replay page; `GET /operator` serves the old page.
* `GET /replay/index` (days, summary, station, model metadata) and `GET /replay/day/<date>` (date matched by
  `\d{4}-\d{2}-\d{2}`), read-only, from `ARTIFACT_URI/replay/`. 404 with `{"available": false}` when not built.
* Page: a Before/After switch (two views), day picker, hour scrubber, play/pause and speed. The map shows the
  houses coloured by status for the selected view; a side panel shows station export and curtailed kWh, the
  limit in force, and whether the interval is in violation. Under the map: a day chart (safe share, fixed,
  model) and a 61-day strip with overload intervals and exported energy, before and after.
* The map module needs no change to its contract if it can colour houses by a status map passed in. If it
  cannot, the smallest change is added to it and its README.

## What the page must say
* The station is simulated: 400 kVA transformer, PV scaled x4, synthetic grid; positions are postcode centres.
* The model was trained without weather and on labels with gaps (see the ML status).
* The twin has no inverter limit. The per-house cap (`share * kwp`) stands in for it; the page must not claim
  inverters were modelled.
* Numbers come from one offline run and were computed on data the model never saw. Results are for scenario A.

## Out of scope
Scenarios B and B-VAR, the weather features, live agent API calls, the 90 houses outside the station, and any
change to the model.

## Risks
* The demo-period score is the final demo evaluation: it is read once, here, and the model is not retrained
  after seeing it.
* The model abstained on 9% of April test intervals; abstained intervals use the fixed limit, so the After view
  shows them as such.
* If the demo numbers are worse than the test ones, the page shows them as they are.

## Tests
* Builder: a small fixture (a few houses, a day) gives the expected status and export values by hand.
* Routes: `/`, `/operator`, `/replay/index`, `/replay/day/<date>` (valid, malformed and missing date).
* Existing UI tests that assert `/` is the operator page are updated to `/operator`.
* Manual: open the page, play a day, check Before and After against the JSON.
