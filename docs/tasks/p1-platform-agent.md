# P1: platform, cloud and agent core

**Owns:** the repository scaffold, `src/common/` (the contract), `src/agent/` (planner, API, action log), `infra/` (Docker, CI, deploy), `Makefile`, `src/grid/thermal.py`, and the cloud. **Reviews** everyone's merges.

Read first: [../08-parallel-plan.md](../08-parallel-plan.md), [../09-contract.md](../09-contract.md), [../10-cloud.md](../10-cloud.md), [../01-theme-and-criteria.md](../01-theme-and-criteria.md).

## Goal
Make the pieces of P2 and P3 work together as **one agent that decides and acts**, and make the whole thing run in the cloud. The agent picks a limit per house, abstains when unsure, asks a human, validates with the guard, executes, logs and explains. You also keep the team unblocked: scaffold first, review fast, integrate early.

## What you deliver
| By gate | Deliverable |
|---|---|
| G0 | Repo scaffold, `.gitignore`, contract, mocks, `make smoke`; budget alarm, bucket, registry |
| G1 | CI; mock-based app deployed at a URL; planner and API on mocks; first end-to-end run on real labels |
| G2 | Abstention queue, approvals, action log; guard integrated; label job running in the cloud; auto-deploy |
| G3 | Training and evaluation in the cloud matching the local run; kill switch; thermal model |
| G4 | Frozen deployed version, health check, HTTPS, runbook, backup video |

## Tasks

### Phase 0 (T+0–1): the scaffold everyone depends on
- Update `.gitignore` so code is tracked: allow `src/`, `tests/`, `infra/`, `pitch/`, `pyproject.toml`, `Makefile`; keep ignoring `data/`, `.venv/`, `results*/`, large files.
- Folders: `src/common`, `src/ml`, `src/grid`, `src/agent`, `src/ui`, `src/eval`, `infra`, `tests`.
- `pyproject.toml` with pinned versions (Python 3.12, pandapower 3.5.6, simbench 1.6.3, scikit-learn 1.9.1, numpy, pandas, a small web stack for the API and UI).
- Contract as code (dataclasses or pydantic) in `src/common/`, plus the four mocks from [09](../09-contract.md).
- `make smoke`: imports everything, loads the mocks, runs one stubbed plan. It must pass before anyone merges.
- Cloud basics ([10](../10-cloud.md)): check the account and access, **set a budget alarm first**, create the private bucket and the registry.
- Announce G0 in the group.

### Phase 1 (T+1–5): planner, deploy, review
- `agent.plan(forecast, grid_state, config) -> plan`: limit per house = cautious quantile (`q05`) × house kWp. If `spread` is above the threshold, set `abstain: true` and use the static fallback (0.36 of kWp).
- Stub guard that always passes (log a warning) until P3's guard lands.
- A small API (read forecast, propose plan, approve, execute, read log, `/health`). All configuration from environment variables ([10](../10-cloud.md)).
- `Dockerfile`, `docker-compose.yml`; GitHub Actions (lint, tests, `make smoke`); deploy the **mock-based app** to the demo host so P3 has a URL from the start; upload the datasets to the bucket.
- **Review P3's merges** (the physics is on the critical path). Ask for the tests listed in P3's file before approving.
- If there are no labels at T+3, take over `safe_share` and move P3 to batteries and the guard.

### Phase 2 (T+5–9): the agent part
- **Abstention queue:** cases flagged "not sure" go to a human with a daily budget (for example "a crew can check N cases per day") shown on screen. Approve or reject; the choice is logged.
- **Guard integration:** call P3's `guard`; if it blocks, the plan is not executed and the log says why.
- **Action log** (append-only JSONL, contract object 4), written through `LOG_URI`. Every decision traceable to the forecast that caused it.
- **Explanations:** from P2's feature contributions, text built from templates using only numbers in the figures. If an LLM is used, it only rephrases those figures; a check rejects text with numbers not in the figures.
- **Cloud:** batch job image; run label generation in parallel on the larger VM and write `labels.parquet` to S3; auto-deploy on merge to `main`.

### Phase 3 (T+9–13)
- Run training and `src/eval/run.py` in the cloud with `ARTIFACT_URI` on S3; check the table matches the local run (same seeds).
- **Kill switch:** pending commands cancelled, houses return to the static fallback. Logged.
- **Transformer thermal model** (`src/grid/thermal.py`) after IEC 60076-7: top-oil and hot-spot temperature, load ratio K, ambient temperature. Parameters are assumed (no measured transformer data); validate the implementation against the worked example in the standard or a published reference, and say so. Dynamic loading: allow short loads above 100% while the hot-spot temperature stays below the limit (a common limit is 98 °C for normal ageing; verify before quoting). Compare with the fixed 100% limit. Cut this first if the core is behind.
- Serve the API to P3's operator screen; keep the contract stable.

### Phase 4 (T+13–17)
- **Feature freeze at T+13:** pin the deployed version, health check, warm instance, HTTPS, read-only demo mode (kill switch and approvals need a demo token).
- Runbook and backup video: record against the cloud URL **and** against a local run.
- Run the demo end to end three times. Own the demo flow: three scenes (normal day, cloud passing, unsure case handled by a human).
- Teardown plan: stop instances, delete what we do not need, remove keys.

## Cloud extras (only after G2 and only if the core works)
Infrastructure as code (Terraform) for everything deployed, scheduled evaluation jobs and a cost report, a retention-locked audit log, deploy checks before replacing the running version, a small monitoring view (health, latency, errors). Good stories for the jury (reproducibility, audit), but none earns points if the ML or the agent does not work.

## Interfaces
- **You consume:** P2's `ml.predict` and evaluation outputs, P3's `power_flow`, `guard` and labels.
- **You provide:** the contract, mocks, the API, the deployed demo and reviews to everyone.

## Definition of done
- The agent visibly **acts** (executes plans, writes the log), not just displays.
- "I am not sure" appears in the demo and goes to a human.
- The guard can block, and the demo shows it once.
- The cloud URL works, a local run works, and the backup video exists.
- No secrets in the repository.

## Pitfalls
- A change to the contract breaks two other people: announce it, update the mocks in the same commit.
- Do not let an LLM decide anything. It may only explain.
- You are the bottleneck in phases 1–2 (scaffold, deploy, planner, reviews). Keep reviews short and the planner small; hand the README to P3 early if needed.
- The cloud is a deployment, not a dependency: everything must still run locally.
- Be explicit on screen about what is simulated (German grid, Australian profiles, assumed batteries and transformer).

## If you fall behind
Keep: scaffold, planner, abstention queue, log, one deployed URL. Cut first: cloud extras, the thermal model, LLM explanations (templates are enough).
