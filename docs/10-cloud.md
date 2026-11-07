# Cloud design

Everything runs in the cloud: the demo, the batch jobs (labels, training, evaluation), the artifacts and the audit log. This file says what we deploy, who owns what, and in which phase. It sits on top of [08-parallel-plan.md](08-parallel-plan.md).

**Cloud owner: P1** (infrastructure and integration touch everything, so the person who owns the agent core and the scaffold owns the cloud). P2 and P3 only follow the rules in "What the others must do".

## Principles
1. **The cloud is a deployment, not a dependency.** The jury runs the project from the README, so `make smoke` and `make eval` must also work on a laptop with no cloud account. The cloud copy is the live demo and the proof that it deploys.
2. **The model runs in our code.** The API container loads the models we trained. No external managed model API makes the prediction (an LLM, if used at all, only rewrites explanations from numbers).
3. **No secrets and no data in the repository.** Keys live in environment variables or the cloud's secret store. Datasets live in a private bucket.
4. **Small and boring.** One region, one small stack, no Kubernetes. If it takes more than a few minutes to explain, it is too complicated for 24 hours.
5. **A cloud failure must not kill the demo.** Backup video and a local run always exist.

## Provider choice
**Default: AWS**, in an EU region (for example `eu-central-1`; assumption, check what the account allows). Reason: PPC's data platform in the deck is on AWS (S3, EMR, Redshift), so the story "this slots into PPC's platform" is easy to tell.

Alternatives if we have no AWS account or credits: any other container host (Fly.io, Render, Hugging Face Spaces) for the demo, with the bucket replaced by object storage of the same provider. The design below does not change; only the service names do.

**To confirm in phase 0:** who has an account, whether the organisers or PPC provide credits, and whether a budget limit exists. Nobody should create resources before a budget alarm is set.

## Architecture

```
GitHub (public repo)
   | push to main
   v
GitHub Actions: lint + tests + make smoke  ->  build images  ->  registry (ECR)
                                                                     |
                     +-----------------------------------------------+
                     v                                               v
          Demo host (one small VM, docker compose)          Batch job (one larger VM, on demand)
          - api (agent + ml.predict + guard)                - labels.py  (power flow, parallel)
          - ui                                              - train.py   (quantile models)
          - reverse proxy + HTTPS                           - eval/run.py (final table)
                     |                                               |
                     +------------------ S3 bucket (private) --------+
                         data/raw  data/labels  models/<version>  eval/  logs/actions.jsonl
```

| Piece | Default | Notes |
|---|---|---|
| Container registry | ECR | One image for the app, one for the batch jobs |
| Demo host | One small VM running `docker compose` (API + UI + reverse proxy) | Simplest to debug live. App Runner or ECS Fargate are fine if someone knows them |
| Batch jobs | One larger VM started on demand, or the same VM at night | Power flow labels parallelise across cores; stop the VM when idle |
| Storage | One private S3 bucket | Layout below |
| CI/CD | GitHub Actions | Lint, tests, smoke, build, and deploy on merge to `main` |
| Secrets | Environment variables from the secret store, `.env` locally (git-ignored) | Never in the repo or in logs |
| Logs | Application logs to the cloud log service; action log (JSONL) to S3 | The action log is the audit trail from the contract |
| Budget | A budget alarm before anything else | Stop and delete resources after the presentation |

## Bucket layout
```
s3://<bucket>/
  data/raw/            downloaded datasets (private, not redistributed)
  data/labels/         labels.parquet per scenario and version
  models/<version>/    model files + metadata.json (git sha, data hash, metrics)
  eval/<run>/          table.csv, table.md, plots
  logs/actions.jsonl   append-only audit log (contract object 4)
```
Every artifact has a version and the git commit that produced it, so the evaluation can be reproduced.

## Configuration (same code locally and in the cloud)
| Variable | Meaning | Local default |
|---|---|---|
| `APP_ENV` | `local` or `cloud` | `local` |
| `DATA_DIR` | Where raw data and labels are read | `./data` |
| `ARTIFACT_URI` | Where models and evaluation outputs go; a path or an `s3://` URI | `./artifacts` |
| `LOG_URI` | Where the action log is appended | `./artifacts/logs/actions.jsonl` |
| `API_URL` | Base URL the UI calls | `http://127.0.0.1:8000` |

## What the others must do (three rules)
- **P2:** training and evaluation scripts read and write through `DATA_DIR` and `ARTIFACT_URI`, take no absolute paths, write `metadata.json` next to every model, and are deterministic (fixed seeds).
- **P3:** the label generator reads and writes through `DATA_DIR` and `ARTIFACT_URI`; the UI reads `API_URL`, nothing is hard-coded to localhost.
- **P1 (owner):** everything else in this file, including the API (`/health`, configuration from the variables above, the action log through `LOG_URI`).

## Cloud track by phase
| Phase | Gate | What gets done (P1 unless stated) |
|---|---|---|
| **0** T+0–1 | G0 | Account and access check, **budget alarm**, bucket, registry, branch protection off (we merge fast). Add `Dockerfile` and `docker-compose.yml` to the scaffold |
| **1** T+1–5 | G1 | GitHub Actions: lint + tests + `make smoke`. First deploy of the **mock-based** app to the demo host so P3 has a URL from the start. Upload the datasets to the bucket |
| **2** T+5–9 | G2 | Batch job image. Run label generation in parallel on the larger VM, write `labels.parquet` to S3 (P2 can also pull it). Auto-deploy on merge to `main` |
| **3** T+9–13 | G3 | Run training and `src/eval/run.py` in the cloud with `ARTIFACT_URI` pointing to S3. The evaluation table in S3 must match the local run (same seeds) |
| **4** T+13–17 | G4 | Feature freeze: pin the deployed version, health check, warm instance, HTTPS, read-only demo mode. Record the backup video against the cloud URL **and** against a local run |
| **5** T+17–18 | | Rehearse on the cloud URL with the venue network. Teardown plan ready |

## Demo-day runbook
1. Deploy the frozen commit at T+13; do not redeploy after T+17 unless something is broken.
2. Check `/health`, one full scene (normal day, cloud passing, unsure case) and the action log write.
3. Keep a local run ready on a laptop and the backup video open.
4. If the cloud URL fails during the demo, switch to the local run without apologising for long.
5. After the presentation: stop instances, delete the bucket data we do not need, remove keys. Keep the repository and the evaluation outputs.

## Security and compliance
- **Data:** only public or synthetic data goes to the bucket, with sources documented ([05](05-data-and-sources.md)). If PPC gives real data, **ask first whether it may leave the premises or the EU**; if the answer is unclear, keep it local and use the cloud for the synthetic pipeline only.
- **Access:** least-privilege roles, a private bucket, no public listing, no long-lived keys in the repo. Rotate or delete keys after the event.
- **Public demo:** read-only, no real customer data, no write endpoints exposed without a token. The kill switch and approvals need a demo token.
- **LLM:** off by default; explanations come from templates. If enabled, it receives aggregates only and every call is logged.
- **Audit log:** append-only JSONL; each decision traceable to the forecast that caused it.

## Cost control
- Budget alarm before the first resource.
- One small VM for the demo, one larger VM only while a batch job runs, stopped afterwards.
- No managed databases or clusters. Everything fits in files and a bucket.
- Check the bill at every sync point.

## Risks
| Risk | Response |
|---|---|
| No cloud account or credits | Use a free-tier container host for the demo and keep batch jobs local; artifacts in the repo release or a bucket on any provider |
| Deploy breaks on Sunday morning | Frozen version at T+13, health check, backup video, local run |
| Network at the venue is slow | Local run as the primary fallback; record the video offline |
| Cloud and local results differ | Same seeds, same container image for the batch job; compare the evaluation table at G3 |
| Cost overrun | Budget alarm, stop idle VMs, delete after the event |
| Cloud work steals time from the core | P1 does the deep cloud work only after `power_flow` and labels exist (G1); at G1 the cloud demo is mock-based on purpose |

## Open questions (settle in phase 0)
- Who owns the cloud account, and what is the budget?
- Does PPC or the organisers provide credits or an environment?
- May any real data leave the premises or the EU?
- Do we need a public URL for the jury, or is a local demo enough? (Ask the organisers; plan for both.)
