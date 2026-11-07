# Demo runbook

How to run the demo, what to say, what to do when something breaks, and how to shut everything down. Owner: P1. It describes what exists today; lines marked **TODO** need data that only exists after a real run.

## Before the demo (30 minutes ahead)

Set two variables in the terminal you will demo from. The token is the `DEMO_TOKEN` secret; keep it in your password manager, never in the repository.
```
URL=https://<the app_url from the last deploy>      # Actions run summary, or terraform output app_url
TOKEN=<demo token>
```
1. `curl -s $URL/health` answers `{"status":"ok","app_env":"cloud","source":...}`. If not, see "When something breaks".
2. `curl -s $URL/kill_switch` says `{"on":false}`. If it is on, switch it off (see below) unless that is the scene.
3. `curl -s $URL/queue` shows the review budget and what is pending. Old plans from rehearsal are fine; the demo uses fresh intervals.
4. A local run is ready as the fallback: `make up`, then `curl -s http://127.0.0.1:8000/health`. Local runs accept writes without a token.
5. The backup video is open in another window.
6. The slide that says what is simulated is ready (see "What to say about the data").

## The three scenes

Replace `<id>` with the `plan_id` returned by each propose call. Every write needs `-H "X-Demo-Token: $TOKEN"` in the cloud.

### Scene 1: a normal day, the agent acts
```
curl -s -X POST $URL/plan/propose -H "X-Demo-Token: $TOKEN" -H 'content-type: application/json' \
  -d '{"interval_start":"2025-06-21T10:00:00Z"}'
```
Show: `source` is `model`, `abstain` is `false`, the limit per house is the cautious quantile (q05) times the house's installed power, `confidence`, and the explanation text. Say that each number in the text is in the figures next to it, and the code refuses text that is not.
```
curl -s -X POST $URL/plan/<id>/approve -H "X-Demo-Token: $TOKEN" -H 'content-type: application/json' -d '{"actor":"operator-demo"}'
curl -s -X POST $URL/plan/<id>/execute -H "X-Demo-Token: $TOKEN" -H 'content-type: application/json' -d '{"actor":"operator-demo"}'
curl -s "$URL/log?limit=5"
```
Show the log: `plan_proposed`, `plan_approved`, `plan_executed`, each with the plan hash, in order.

### Scene 2: a cloud passes, the agent is not sure
Propose an interval where the forecast is wide. With the mock source that is the night: `"interval_start":"2025-06-21T02:00:00Z"`. **TODO:** with `SOURCE=model`, use the cloudy interval found in the evaluation (from `src/eval/error_analysis.py`) instead, and say which day it is.

Show: `abstain` is `true`, `source` is `fallback_static`, the limit is the fixed 36% of installed power, `confidence` is low, `reasons` says the spread is above the threshold (0.30), and the explanation says a person reviews the case. The agent did not guess; it fell back to the old rule and asked.

### Scene 3: a person handles the unsure case
```
curl -s $URL/queue
```
Show: the pending case, how many cases were reviewed today, the daily budget (20) and how many remain. Then approve or reject:
```
curl -s -X POST $URL/plan/<id>/approve -H "X-Demo-Token: $TOKEN" -H 'content-type: application/json' -d '{"actor":"operator-demo"}'
```
Show the log: the `abstained` event and the decision, with the review counters in `detail`.

### The guard blocks a plan (one moment)
With `SOURCE=model` the real grid guard runs and fails closed: it rejects a plan it cannot verify (for example without a PV and load forecast). **TODO:** after a real run, pick the interval where it rejects a plan on voltage or transformer limits (`python -m src.agent.replay` lists plans with their status), show the `guard_blocked` event with its violations, and say that nothing was executed.

### The kill switch (optional, short)
```
curl -s -X POST $URL/kill_switch -H "X-Demo-Token: $TOKEN" -H 'content-type: application/json' -d '{"on":true,"actor":"operator-demo"}'
curl -s -X POST $URL/plan/<id>/execute -H "X-Demo-Token: $TOKEN" -H 'content-type: application/json' -d '{"actor":"operator-demo"}'   # 409
curl -s -X POST $URL/kill_switch -H "X-Demo-Token: $TOKEN" -H 'content-type: application/json' -d '{"on":false,"actor":"operator-demo"}'
```
Show: every pending or approved plan is cancelled, with one `plan_rejected` event each, execution is refused, and the fixed share is logged as the fallback. Be clear that nothing is connected to real devices: the log is the action.

## What to say about the data
- The grid is a German SimBench grid and the household profiles are Australian (Ausgrid), rescaled. It is a simulation, not PPC's network.
- Batteries and the transformer thermal parameters are assumed.
- The 1.05 pu limit comes from a press summary and is unverified. We do not know whether the rules allow a variable limit per prosumer.
- Until the model and grid twin are connected, the numbers in the live app come from a mock source. Say so.

## When something breaks

| Symptom | Cause | Fix |
|---|---|---|
| `/health` does not answer | app not running or still starting | wait a minute; check the Container App in the portal; otherwise switch to the local run (`make up`) and say so briefly |
| Write returns 503 | the app is in the cloud and has no token set | the deploy requires the `DEMO_TOKEN` secret; set it and run the deploy again |
| Write returns 403 | wrong or missing `X-Demo-Token` | use the right token |
| 409 on approve, reject or execute | the plan is not in the right status, or the kill switch is on | `curl -s $URL/plan/<id>`; a rejected plan stays rejected |
| 404 on a plan | unknown `plan_id` | copy it from the propose response; ids are `PLAN-<UTC time>-<station>` |
| The same plan comes back | proposing is idempotent per half-hour slot | use another interval |
| Write returns 500 | most likely the action log cannot be written | an action is refused when its audit event cannot be written; check the file share and the container logs |
| The app restarted | deploy, crash or move | state is rebuilt from the action log: plans, the review count and the kill switch come back. Check `curl -s $URL/kill_switch` |

If the cloud URL fails during the demo, switch to the local run without apologising for long.

## Freeze and redeploy
- Feature freeze at T+13, code freeze at T+17: after T+13 only `fix:` and `docs:` merges; after T+17 nothing merges unless the demo is broken.
- Deploy runs on every merge to `main` when `DEPLOY_ENABLED=true`. To redeploy the same commit: Actions, `ci`, Run workflow on `main`. To go back to an older version, revert the commit on `main`; the pipeline deploys the result.
- The image tag is the commit hash, so the deployed version is always visible in the container app's revision.

## Backup video
Record two takes of the three scenes: one against the cloud URL and one against the local run. Keep the files outside the repository (they are large) and have both open before the presentation.

## Shut down after the event
Do this after the presentation, in this order. The repository and the evaluation outputs stay.
1. Stop deploys first: `gh variable set DEPLOY_ENABLED --body false`. Otherwise a late merge to `main` redeploys the stack while you are tearing it down (the `batch` workflow stops too).
2. Download the evaluation outputs you want to keep from the `artifacts` share of the storage account (portal, or `az storage file download-batch`).
3. Destroy the stack: with `infra/terraform/backend.hcl` in place, run `make tf-init`, then `terraform -chdir=infra/terraform destroy`. If that fails, delete the resource group instead: `az group delete --name rg-ppcsmart-demo --yes`.
4. Delete the state: `az group delete --name rg-ppcsmart-tfstate --yes`.
5. Delete the identities the bootstrap script created:
   ```
   for NAME in ppc-smarthack-github ppc-smarthack-github-plan; do
     az ad app list --display-name "$NAME" --query '[].appId' -o tsv | xargs -I{} az ad app delete --id {}
   done
   ```
6. Remove the GitHub secrets and variables (Settings, Secrets and variables, Actions), or run `gh secret delete` and `gh variable delete` for each.
7. Check in the portal that no resource group of ours is left and that the cost view is flat.
