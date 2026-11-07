# Demo script (about 5 minutes)

Everything on screen is simulated, and the screen says so. Say it first: "This is a model of one station, not PPC's network, and nothing here controls a real inverter."

## Before you start (once)
Terminal 1, agent API with the real grid guard:
```sh
python -m uvicorn src.grid.demo_api:app --port 8000
```
Terminal 2, operator screen:
```sh
API_URL=http://127.0.0.1:8000 python -m uvicorn src.ui.app:app --port 8001
```
Open http://127.0.0.1:8001 and set the day to today (UTC). Reset the log between rehearsals by deleting the file in `LOG_URI` (default `artifacts/logs/actions.jsonl`) and restarting the API.

**Status of the data source:** until P2's model is connected the API runs on `SOURCE=mock`, a synthetic forecast. Say "mock forecast" out loud. Once the model is in, the same scenes run on the real forecast; re-check the times below, because they depend on the forecast.

## Scene 1: a normal day (midday)
1. Slide the interval to **10:00 UTC**. Point at the forecast band: the cautious value (q05) against the fixed 36% line, and the small spread.
2. Click **Propose plan**. Show the green houses, the limit in kW per house, the text explanation and "Guard passed" with the voltage and transformer load.
3. Say: "Each house may export more than the fixed limit, and the guard checked the whole station with its own power flow before anything is allowed."
4. Click **Approve**, then **Execute**. Open the action log: proposed, approved, executed, each with actor and plan id.

## Scene 2: uncertainty rises, the agent steps back
1. Slide to **05:30 UTC** (or **15:00 UTC**): the band is wide and the spread is above the 30% threshold. With the real model this is the cloud-passing case; with the mock it is a wide band at the edge of the day.
2. Click **Propose plan**. The houses turn yellow: the limit falls back to the fixed 36% and confidence drops.
3. Say: "When the model is unsure, it does not guess. It applies today's fixed limit and sends the case to a person."

## Scene 3: a person decides
1. In **"Not sure" queue**, the case from scene 2 is waiting. Show the counter, for example "reviewed today 0/20": the crew has a review budget, and the screen shows when it is exceeded.
2. Click **Reject** (or **Approve**). Show the new line in the action log with the actor.
3. Optional: turn on the **kill switch**. Open plans are cancelled and the log records one event per plan. Turn it off.

## Bonus scene: the guard blocks a plan
Restart the API with a deliberately weak transformer:
```sh
TRANSFORMER_KVA=20 python -m uvicorn src.grid.demo_api:app --port 8000
```
Propose at 10:00 UTC. The plan turns red: "Transformer loading exceeds 100%". Say: "Even a plan from the model cannot go out if the physics says no."

## Comparison panel
Scroll to "Fixed limit versus ours". The numbers come from `summary.json` written by the evaluation script, not from the page. If it says "No evaluation output yet" or "MOCK, NOT A RESULT", do not quote any figure; run `python -m src.eval.run` first.

## What not to claim
- No claim of results on PPC's network. The grid is synthetic and the profiles are Australian.
- No claim that rules allow variable limits per prosumer: that is an open question for the operator and ANRE.
- Do not quote the exploration table from `docs/04-chosen-idea.md` as a result; it comes from local code that is not in this repository. Quote only the evaluation output.
- The guard is a simulation check, not a certified protection system.
