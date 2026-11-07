# Cloud design: Docker, Terraform, Azure

Everything is containerised, and everything that runs in the cloud is created by Terraform on Azure and deployed automatically by GitHub Actions. This file says what we deploy, how, and who owns what. It sits on top of [08-parallel-plan.md](08-parallel-plan.md).

**Cloud owner: P1** (infrastructure and integration touch everything, so the person who owns the agent core and the scaffold owns the cloud). P2 and P3 only follow the rules in "What the others must do".

## Principles
1. **Everything runs in a container.** The app, the tests and the lint run from the same Dockerfile. If it works in the container locally, it works in the cloud.
2. **Infrastructure is code.** No clicking in the portal. Terraform creates and changes every Azure resource, except the one-time bootstrap script.
3. **Merging to `main` deploys.** The pipeline tests, builds, pushes the image and applies Terraform. A failed health check fails the pipeline.
4. **The cloud is a deployment, not a dependency.** The jury runs the project from the README, so `make smoke`, `make test` and the evaluation must also work locally (with or without Docker). The cloud copy is the live demo.
5. **The model runs in our code.** The API container loads the models we trained. No external model API makes the prediction (an LLM, if used at all, only rewrites explanations from numbers).
6. **No secrets and no data in the repository.** Secrets live in GitHub secrets and Azure; datasets stay out of the repo.
7. **Small and boring.** One region, one environment, no Kubernetes.

## What runs where
```
GitHub (public repo)
   | push / PR
   v
GitHub Actions
  test (pip)   docker (tests + lint + smoke inside the image)   terraform (fmt + validate)
  plan (PRs to main from this repo only: read-only identity, terraform plan without refresh, summary on the run page)
   | all green, on main, DEPLOY_ENABLED=true
   v
deploy job (Azure login with OIDC, no stored secret)
  1. terraform apply -target=azurerm_container_registry   (the registry must exist first)
  2. docker build + push  ppc-smarthack:<git sha>
  3. terraform apply                                       (container app uses the new tag)
  4. curl /health                                          (fail the job if it never answers)

Azure resource group  rg-ppcsmart-demo
  Container Registry (Basic)        image storage
  Container Apps environment        logs go to Log Analytics
    Container App "api"             1 replica, HTTPS ingress, managed identity pulls the image
  Storage account + file share      mounted at /data/artifacts (action log, models, evaluation outputs)
  Budget (optional)                 alerts at 80% actual and 100% forecast
```

| Piece | Choice | Why |
|---|---|---|
| Compute | Azure Container Apps | Runs a container with HTTPS and no cluster to manage |
| Registry | Azure Container Registry, Basic | Image storage next to the app; the app pulls with a managed identity, no password |
| Storage | Storage account, Azure Files share mounted into the container | The action log and artifacts stay plain file paths (`LOG_URI`, `ARTIFACT_URI`), so the same code runs locally and in the cloud |
| Logs | Log Analytics workspace | Container logs without extra setup |
| Secrets | `DEMO_TOKEN` as a Container Apps secret, passed from a GitHub secret | Never in the repository or in Terraform files |
| State | Terraform state in a separate storage account, created by the bootstrap script | State must live outside the stack it describes |
| Region | `germanywestcentral` by default (variable) | EU region allowed by the Azure for Students region policy; change it in `variables.tf` and `bootstrap.sh` |

The app runs with **exactly one replica** because the action log is a single append-only file on a shared volume.

## Files
| Path | What it is |
|---|---|
| `infra/Dockerfile` | Multi-stage: `base`, `dev` (tests and lint) and `app` (runtime, non-root) |
| `infra/docker-compose.yml` | `api` for running, `test` and `lint` (profile `test`) for checks |
| `infra/terraform/` | `versions.tf`, `variables.tf`, `main.tf`, `outputs.tf`, `.terraform.lock.hcl` |
| `infra/azure/bootstrap.sh` | One-time setup: state storage and the GitHub OIDC identity |
| `.github/workflows/ci.yml` | `test`, `docker`, `terraform` and `deploy` jobs |
| `Makefile` | `make docker-build`, `up`, `down`, `docker-test`, `tf-validate`, `tf-init`, `tf-plan`, `tf-apply` |

## Local use
```
make up            # run the API in Docker at http://127.0.0.1:8000
make docker-test   # tests and lint inside the container
make tf-validate   # Terraform validation, no Azure access needed
```

## One-time setup (a person with Owner rights on the subscription)
1. Install the Azure CLI, run `az login`.
2. Run `SUBSCRIPTION_ID=<id> GITHUB_REPO=owner/repo infra/azure/bootstrap.sh`. It creates the state storage and two identities that GitHub can use through OIDC (one for deploys from `main`, one read-only for the plan job on pull requests), then prints the values to store. It needs `gh` logged in: it reads the OIDC subject prefix GitHub uses for this repository (new repositories use the immutable form `repo:owner@<id>/repo@<id>`).
3. In the GitHub repository settings add the printed **secrets** (`AZURE_CLIENT_ID`, `AZURE_PLAN_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `DEMO_TOKEN`) and **variables** (`DEPLOY_ENABLED=true`, `TFSTATE_RG`, `TFSTATE_SA`, `TFSTATE_CONTAINER`).
4. Optional, for local Terraform: create `infra/terraform/backend.hcl` (git-ignored) as the script prints, then `make tf-init` and `make tf-plan`.
5. Optional budget alert: set the repository variable `BUDGET_EMAILS` to a JSON list, for example `["you@example.com"]` (Settings, Secrets and variables, Actions, Variables, or `gh variable set BUDGET_EMAILS --body '["you@example.com"]'`). The deploy and the plan job pass it to Terraform; empty or unset means no budget. Whether a Students subscription accepts a budget is not verified: if the apply refuses it, clear the variable.

The first push to `main` after this creates the whole stack.

## Configuration (same code locally and in the cloud)
| Variable | Meaning | Local default | In the cloud |
|---|---|---|---|
| `APP_ENV` | `local` or `cloud` | `local` | `cloud` |
| `DATA_DIR` | Where raw data and labels are read | `./data` | files on the mounted share |
| `ARTIFACT_URI` | Where models and evaluation outputs go; a path | `./artifacts` | `/data/artifacts` (the Azure Files share) |
| `LOG_URI` | Where the action log is appended; a path | `./artifacts/logs/actions.jsonl` | `/data/artifacts/logs/actions.jsonl` |
| `API_URL` | Base URL the UI calls | `http://127.0.0.1:8000` | the Container App URL (Terraform output `app_url`) |
| `SOURCE` | `mock` until the real model and grid are connected | `mock` | `mock` |
| `DEMO_TOKEN` | Required header `X-Demo-Token` for write endpoints; empty disables the check | empty | secret from GitHub |

Layout on the share:
```
/data/artifacts/
  data/raw/            downloaded datasets (private, not redistributed)
  data/labels/         labels.parquet per scenario and version
  models/<version>/    model files + metadata.json (git sha, data hash, metrics)
  eval/<run>/          table.csv, table.md, plots
  logs/actions.jsonl   append-only audit log (contract object 4)
```

## What the others must do
- **P2:** training and evaluation scripts read and write through `DATA_DIR` and `ARTIFACT_URI` (plain paths), take no absolute paths, write `metadata.json` next to every model, and are deterministic (fixed seeds).
- **P3:** the label generator reads and writes through `DATA_DIR` and `ARTIFACT_URI`; the UI reads `API_URL`, nothing is hard-coded to localhost, and it ships as its own service in `infra/docker-compose.yml` (P1 adds it to Terraform when it exists).
- **P1 (owner):** everything else in this file.

## Cloud track by phase
| Phase | Gate | What gets done (P1 unless stated) |
|---|---|---|
| **0** T+0–1 | G0 | Dockerfile, compose, Terraform, CI and the bootstrap script are in the repo (done on branch `platform/scaffold`); account access and a **budget alert** |
| **1** T+1–5 | G1 | Run the bootstrap, add the GitHub secrets, first automatic deploy of the **mock-based** app, so P3 has a URL |
| **2** T+5–9 | G2 | Batch runs in the same image (`docker compose run`, or a Container Apps job) for labels; datasets on the share |
| **3** T+9–13 | G3 | Training and `src/eval/run.py` run in the container with `ARTIFACT_URI` on the share; the table matches the local run |
| **4** T+13–17 | G4 | Feature freeze: pin the deployed image tag, check `/health`, read-only demo mode, backup video recorded on the cloud URL **and** locally |
| **5** T+17–18 | | Rehearse on the cloud URL with the venue network. Teardown plan ready (`terraform destroy`) |

## Demo-day runbook
1. Deploy the frozen commit at T+13; do not deploy again after T+17 unless something is broken.
2. Check `/health`, one full scene (normal day, cloud passing, unsure case) and that the action log is written.
3. Keep a local run (`make up`) on a laptop and the backup video open.
4. If the cloud URL fails during the demo, switch to the local run without apologising for long.
5. After the presentation: `terraform destroy` (or delete the resource group), remove the identity created by the bootstrap script, keep the repository and the evaluation outputs.

## Security and compliance
- **Data:** only public or synthetic data goes to the share, with sources documented ([05](05-data-and-sources.md)). If PPC gives real data, **ask first whether it may leave the premises or the EU**; if unclear, keep it local and use the cloud for the synthetic pipeline only.
- **Access:** the app pulls its image with a managed identity (role `AcrPull`), the registry has no admin user, the state storage has no public blob access, GitHub authenticates with OIDC and no long-lived key.
- **Two identities:** the deploy identity (logins from `main` only) gets Contributor and User Access Administrator on the subscription so that Terraform can create role assignments; narrow it to the resource group if the policy requires it. The plan identity (logins from pull requests) gets Reader on the subscription and Storage Blob Data Reader on the state account only, because a pull request can change the workflow and Terraform files and runs them before review. Its plan does not refresh and does not lock the state, so it shows the difference between the code and the last applied state, not drift in Azure. The `DEMO_TOKEN` is not passed to it.
- **Public demo:** read-only unless `X-Demo-Token` is given; the kill switch and approvals are writes. In the cloud the API refuses every write when no token is set, and the deploy job fails when the `DEMO_TOKEN` secret is empty.
- **LLM:** off by default; explanations come from templates. If enabled, it receives aggregates only and every call is logged.
- **Audit log:** append-only JSONL; each decision traceable to the forecast that caused it.

## Cost control
- Budget alert: set the `BUDGET_EMAILS` repository variable before the first deploy.
- Container Apps Basic-tier pieces only: one 0.5 vCPU / 1 GiB replica, Basic registry, LRS storage. Check the bill at every sync point.
- Everything is deleted after the event.

## Status: what is verified and what is not
| Item | Status |
|---|---|
| Terraform formatting and `terraform validate` against azurerm 4.x | Verified locally |
| `docker compose config` | Verified locally |
| Workflow YAML parses; `bootstrap.sh` passes `bash -n` | Verified locally |
| `make docker-test` (40 tests and lint in the `dev` image) and `make docker-build` | Verified locally |
| Runtime image: `python -m src.smoke`, `/health`, container health check, propose → approve → execute, action log written by the non-root user to the named volume and kept across a restart | Verified locally with `docker compose` (not on Azure Files) |
| `terraform plan` or `apply` against a real subscription | **Not run**: no Azure access from here |
| `bootstrap.sh` against a real tenant | **Not run** (Azure CLI not installed here) |
| Azure Files mount permissions for the non-root user (`mount_options` in `main.tf`) | **Unverified until the first deploy**; if the log cannot be written, change the mount options or the container user |
| The deploy job | **Never run**; expect to fix small things on the first real deploy |

## Risks
| Risk | Response |
|---|---|
| No Azure subscription or credits | Run `make up` locally and the container on any host; Terraform stays in the repo as the deployment recipe |
| First deploy fails on Sunday | Do the first deploy on Saturday evening, not at T+13; keep the backup video and the local run |
| Azure Files mount is not writable | Adjust `mount_options` or run the container as root for the demo |
| Container Apps rejects the first image pull because the role assignment is not ready | Re-run the deploy job; the `depends_on` usually covers it |
| Cloud work steals time from the core | The deep cloud work happens after `power_flow` and labels exist (G1); the first deploy is mock-based on purpose |

## Open questions
- Who has the Azure subscription, and what is the budget? Does PPC or the organisers provide credits?
- May any real data leave the premises or the EU?
- Do we need a public URL for the jury, or is a local demo enough? (Ask the organisers; plan for both.)
