# P6 requests to P1 (agent)

What the model side now provides, and what the agent needs to do with it. None of this is
done in `src/agent/` yet; P1 decides how (this follows step 09 of [p6-ml-v2.md](p6-ml-v2.md)).

## 1. Keep the online offset per station
`safe-cap-qgb-v2` saves the offset it ended its replay with: `metadata.json` → `offset.c_start`,
with the step size `offset.gamma` and the target `offset.alpha`. The limit to send is
`clip(q05 - c, 0, 1)`; `src.ml.online_calibration.Offset` holds `c` and has `apply`, `update`,
`to_dict` and `from_dict`.

- Start a station at `c_start`.
- Thirty minutes after an interval ends its safe share is known: call `update(limit, safe_share)`
  for the intervals where the model limit was applied (not for abstained ones, not for an unknown
  share).
- Keep `to_dict()` between calls, for example one small JSON per station.
- Pass the live value to the explanation as `offset_c` in the features given to
  `ml.explain.explain`; without it the explanation shows the saved start value.

## 2. Log the rolling rates
Log the violation rate (limits that were above the realised safe share) and the abstention rate
over the last 7 days, per station.

## 3. Alert above the target
Raise an alert when the rolling violation rate is above `alpha` (`offset.alpha`, the
`VIOLATION_TARGET`). It is an action in the theme's sense: a person looks at the station.

## 4. Optional: stations to check today
A list ordered by the size of the offset and the number of abstentions, so the crew
(`CREW_CASES_PER_DAY`) starts with the stations whose model has drifted most.

## What is already in place
- The input checks abstain live (`missing_net_now`, `stale_input`, `out_of_range_net`) and the
  reasons reach the plan (step 11).
- The transformer hot-spot uses the measured temperature when the weather file is there
  (step 12).
- The guard and the kill switch are unchanged: no limit is sent without the guard's pass.
