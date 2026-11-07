# Contract: the shared interfaces

Everyone builds against these objects from minute one, using the mock examples below. Owned by P1 (`src/common/`). A change is announced to the group first and the mock is updated in the same commit.

Conventions:
- Times are UTC ISO 8601. Power is in kW, energy in kWh, voltage in per unit (pu, 1.00 = 230 V) unless the field name says `_v`.
- `null` means missing, never 0.
- Every record has `provenance`: `measured`, `simulated`, `forecast` or `assumed`.
- Every record that depends on the past has `available_at`: the moment the information existed. Training and evaluation use only records with `available_at <= decision time`.

## 1. `forecast`: output of P2's models

One record per station and interval. `horizon_min` is how far ahead it looks (60 for the safe cap, longer for PV and load used by batteries).

```json
{
  "pt_id": "PT-A",
  "interval_start": "2025-06-21T10:00:00Z",
  "horizon_min": 60,
  "safe_cap_share": {"q05": 0.52, "q10": 0.55, "q20": 0.58, "q50": 0.64, "q90": 0.71},
  "spread": 0.19,
  "pv_kw": {"p10": 41.0, "p50": 58.5, "p90": 70.2},
  "load_kw": {"p10": 12.1, "p50": 15.3, "p90": 21.0},
  "available_at": "2025-06-21T09:00:00Z",
  "model_version": "safe-cap-qgb-v1",
  "provenance": "forecast",
  "source_ref": "ml/train.py@<git sha>"
}
```
- `safe_cap_share` is the highest export limit that will be safe, as a share of each house's installed kWp (0 to 1). Quantile `q05` is the cautious value the planner uses.
- `spread = q90 − q05` is the uncertainty used for the "not sure" rule. The code rejects a record whose spread does not match, and one whose quantiles cross (sort them before returning).
- Times must carry a time zone (UTC); naive datetimes are rejected.
- `pv_kw` and `load_kw` are totals for the station; they may be `null` in phase 1.

## 2. `grid_state`: output of P3's twin (thermal fields by P1)

```json
{
  "pt_id": "PT-A",
  "interval_start": "2025-06-21T10:00:00Z",
  "converged": true,
  "v_max_pu": 1.043,
  "v_max_node": "bus-17",
  "line_loading_max_pct": 63.0,
  "trafo_loading_pct": 88.0,
  "trafo_hotspot_c": 92.5,
  "batteries": [{"house_id": "H03", "soc_kwh": 6.4, "power_kw": 2.5}],
  "exported_kwh": 12.4,
  "curtailed_kwh": 1.1,
  "provenance": "simulated"
}
```
`trafo_hotspot_c` is `null` until the thermal model exists.

## 3. `plan`: output of P1's planner, checked by P3's guard

```json
{
  "plan_id": "PLAN-2025-06-21-1000-PT-A",
  "pt_id": "PT-A",
  "interval_start": "2025-06-21T10:00:00Z",
  "limits": [
    {"house_id": "H01", "export_limit_kw": 2.6, "battery_kw": 0.0},
    {"house_id": "H02", "export_limit_kw": 4.16, "battery_kw": 0.0}
  ],
  "safe_cap_share_used": 0.52,
  "source": "model",
  "abstain": false,
  "confidence": 0.683,
  "reasons": ["spread 0.19 below threshold 0.30"],
  "guard": {"passed": true, "v_max_pu": 1.041, "trafo_loading_pct": 86.0, "violations": []},
  "explanation": {
    "text": "Each house may export up to 52% of its installed power. The model's uncertainty is 19%, below the 30% threshold, so its cautious estimate replaces the fixed 36% limit.",
    "figures": [
      {"name": "export_limit_pct", "value": 52},
      {"name": "uncertainty_pct", "value": 19},
      {"name": "threshold_pct", "value": 30},
      {"name": "static_limit_pct", "value": 36}
    ]
  },
  "status": "proposed"
}
```
(Shortened: the full mock lists every house of the station.)
- `source` is `model` or `fallback_static`.
- Limit per house = share × installed kWp, capped by the house's contract limit (`contract_cap_kw`, the approved evacuation power, which stays a ceiling).
- `confidence = 1 − spread / (2 × threshold)`, clipped to [0, 1]: 0.5 at the threshold, 0 when there is no usable forecast.
- Explanation text may only contain numbers that appear in its `figures`; the code refuses to show it otherwise.
- `abstain: true` means the case goes to a human; the limit actually applied is the static fallback.
- `status`: `proposed` → `approved` / `rejected` → `executed`.

## 4. `action_event`: the audit log (append-only JSONL)

```json
{
  "ts": "2025-06-21T10:00:03Z",
  "plan_id": "PLAN-2025-06-21-1000-PT-A",
  "event": "plan_approved",
  "actor": "operator-demo",
  "detail": {"abstain": false},
  "plan_sha": "9f2c4a7e1b0d3c58"
}
```
`event` is one of `plan_proposed`, `guard_blocked`, `plan_approved`, `plan_rejected`, `plan_executed`, `abstained`, `kill_switch`. Each decision must be traceable from the log to the forecast that caused it.

The log is also the agent's memory. `plan_proposed` and `guard_blocked` carry the full plan in `detail.plan`; at start-up the service replays the log to rebuild its plans, the review count and the kill switch. An event is written before the state it describes changes, so a failed write leaves the state as it was. The kill switch writes one `plan_rejected` event (`detail.reason = "kill_switch"`) per cancelled plan, then the `kill_switch` event. A plan the operator rejected stays rejected; a plan blocked by the guard or cancelled by the kill switch can be proposed again. Unreadable lines (for example one cut short by a crash) are skipped.

## 5. `station_config`: the station the agent controls

```json
{
  "pt_id": "PT-A",
  "houses": [
    {"house_id": "H01", "kwp": 5.0},
    {"house_id": "H06", "kwp": 25.0, "contract_cap_kw": 9.0}
  ],
  "static_share": 0.36,
  "spread_threshold": 0.30,
  "review_budget": 20
}
```
`static_share` is the fixed limit used as fallback, `spread_threshold` is the "not sure" cut-off, and `review_budget` is how many unsure cases a crew can review per day.

## Reference implementation

The contract lives in code in `src/common/contract.py` (pydantic models, mocks in `src/common/mocks/`). The agent API serves it: `GET /health`, `/station`, `/forecast`, `/grid_state`, `/plans`, `/plan/{id}`, `/queue`, `/log`, `/kill_switch`, and `POST /plan/propose`, `/plan/{id}/approve`, `/plan/{id}/reject`, `/plan/{id}/execute`, `/kill_switch`. Writes need the header `X-Demo-Token` when `DEMO_TOKEN` is set; with `APP_ENV=cloud` and no token every write is refused (503). `actor` in a request is self-asserted: with one shared token it names a role, not an authenticated person. Run it with `make run`.

## Function interfaces

These are the Python entry points other people call. Signatures can be refined, the semantics cannot change without announcing it.

| Owner | Function | Meaning |
|---|---|---|
| P2 | `ml.predict(features) -> forecast` | Predictions with quantiles for one station and interval |
| P2 | `ml.features.build(station_state, t) -> features` | Only information available at time `t` |
| P3 | `grid.build_grid(config) -> Grid` | SimBench grid plus houses, panels, batteries |
| P3 | `grid.power_flow(grid, injections) -> grid_state` | One AC power flow |
| P3 | `grid.safe_share(grid, injections) -> float` | The label: highest share in [0, 1] that respects the limits |
| P3 | `grid.guard(grid, plan, injections) -> {passed, violations}` | Checks a plan with its own power flow |
| P1 | `grid.thermal.step(state, load_ratio, ambient_c) -> hotspot_c` | Transformer hot-spot temperature after one step |
| P1 | `agent.plan(forecast, grid_state, config) -> plan` | Decision, with abstention and fallback |
| P1 | `agent.execute(plan, user) -> action_event[]` | Applies an approved plan and logs it |

## Mocks
`src/common/mocks/` contains one valid example of each object (the ones above). The first commit of the repository (gate G0) includes them. Anything that is not covered by the contract waits.
