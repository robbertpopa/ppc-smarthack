# PPC Smarthack XI 2026: dynamic export limits for prosumers

Our project for the PPC theme **"24h to Power PPC: AI in energy, from data to action"**. An agent decides, every 30 minutes, how much each house under a transformer station may export to the grid. It uses an ML model we trained: quantile regression one hour ahead. When the model is unsure, the agent falls back to the fixed limit and sends the case to a person. Everything is simulated: the grid is synthetic and the household data is Australian (Ausgrid). Nothing controls real inverters.

## What the theme asks for, and where it is
| Theme requirement | Where |
|---|---|
| ML model trained by the team, code in the repo, runs in our code | `src/ml/train.py`, `src/ml/predict.py` (scikit-learn, no external API) |
| Separate test set, compared with a simple baseline | `src/eval/run.py`: test year 2012-07-01 → 2013-06-30; baselines fixed limit, last known, same hour yesterday |
| The agent acts: prioritises, alerts, plans | `src/agent/`: plan per house, approve / reject / execute, review queue, kill switch, action log |
| "I am not sure" sent to a person | `src/ml/abstention.py` and the review queue (`/queue`) |
| Explainability | `src/ml/explain.py`: top factors and similar past cases, added to each plan's explanation |
| Data sources stated | section "Data and sources" below |
| Reproducible from the README with our evaluation script | sections 1–9 below |

## Run it locally
Every command below was run on 2026-11-08 on macOS with Python 3.12.12; the times come from that machine. Commands are for macOS and Linux; Windows notes are at the end of this section.

### 1. Requirements
- Python 3.12 and git.
- About 1 GB of free disk for the data and models, and internet for the one-time data download.

### 2. Install
```bash
python3.12 -m venv .venv
```
```bash
source .venv/bin/activate
```
```bash
python -m pip install -e ".[dev,ml,sim,grid-tools]"
```

### 3. Check that everything works
| Check | Command | Expected |
|---|---|---|
| Tests | `python -m pytest -q` | all pass (353 tests, about 2 minutes) |
| Lint | `python -m ruff check src tests` | `All checks passed!` |
| Smoke | `python -m src.smoke` | `SMOKE OK` |

### 4. Demo without any data
Two terminals:
```bash
python -m uvicorn src.grid.demo_api:app --port 8000
```
```bash
API_URL=http://127.0.0.1:8000 python -m uvicorn src.ui.app:app --port 8001
```
Open http://127.0.0.1:8001 (operator screen). The API uses mock forecasts and the real grid guard; its documentation is at http://127.0.0.1:8000/docs.

### 5. Data
```bash
python -m src.ml.data download
```
```bash
python -m src.ml.data profiles
```
This writes `DATA_DIR/raw/ausgrid/` and `DATA_DIR/profiles.parquet` (about 40 s). `--from PATH` uses a local zip or folder instead of the network. The 2012–13 file is the sealed test year: it is skipped unless you pass `--include-held-out`, which is for the final evaluation only (section 9).

### 6. Labels
```bash
python -m src.ml.labels mock --scenario A
```
This writes mock labels with the real schema to `DATA_DIR/labels/A/`. The scenarios are `A`, `B` and `B-VAR`. Real labels come from the power flow (`python -m src.grid.labels`), but its output does not yet match the schema the training reads. Until it does, training runs on mock labels and its numbers are not results.

### 7. Train
```bash
python -m src.ml.train --scenario A
```
```bash
python -m src.ml.forecast_pv_load --scenario A
```
These take about 45 s and 40 s. The models and `metadata.json` go to `ARTIFACT_URI/models/<version>/PT-A/`.

### 8. The agent on the trained model
```bash
SOURCE=model SCENARIO=A python -m uvicorn src.agent.api:app --port 8000
```
Start the screen as in section 4. On the screen, pick a day inside the label period, for example 2012-01-15; the 02:00 UTC slot is 13:00 in Sydney. On other days the model has no recent readings, so its forecast means nothing.

### 9. Reproduce the results (evaluation)
The evaluation scores the test year, 2012-07-01 → 2013-06-30. Before running it:
1. Download the held-out year: `python -m src.ml.data download --include-held-out`.
2. Rebuild the profiles: `python -m src.ml.data profiles`.
3. Generate labels that cover that year.

Then run:
```bash
python -m src.eval.run --scenario all --run-id final --error-analysis
```
The output goes to `ARTIFACT_URI/eval/final/`. The screen's comparison panel reads its `summary.json` when started with `EVAL_RUN_ID=final`. Every number in the presentation comes from this output. `python -m src.common.pipeline --run-id final` runs training, the PV/load forecast and the evaluation in one command.

### 10. Prices and the prosumer price comparison (optional)
The evaluation can compare what battery owners earn today on an older compensation contract (the regulated monthly average price) and on PPC's MaxControl (the 15-minute spot price minus the injection tariff) with an hourly price plus a monthly solar adder, and what each does to PPC's margin. It needs one year of Romanian day-ahead prices from [euenergy.live](https://euenergy.live) (CC-BY-4.0, free token). Put `EUENERGY_TOKEN=<your token>` in `.env` (the file is not committed), then:
```bash
set -a; . ./.env; set +a
python -m src.pricing.prices fetch --year 2025
python -m src.eval.run --pricing
```
The first command saves `data/pzu/ro.parquet`. The second adds a `pricing` block to `summary.json`, a `pricing_<station>.md` table and a `pricing_day_<station>.png` chart. Prices are matched to the Ausgrid year by season (Sydney July with Bucharest January) and local hour, so the result shows the shape of the effect, not a forecast in euros. Fee, floor and bonus share are placeholders in `src/pricing/config.py`.

If the PV/load forecast is trained (`python -m src.ml.forecast_pv_load --scenario A`), the table also shows the imbalance savings of that forecast against "same time yesterday" for three imbalance spreads (30, 60 and 120 EUR/MWh, scenario values, not market data) and the bonus prosumers would get. Without the trained model that part is skipped.

### Environment variables
| Variable | Default | Used for |
|---|---|---|
| `DATA_DIR` | `./data` | raw data, profiles, labels |
| `ARTIFACT_URI` | `./artifacts` | models and evaluation output |
| `LOG_URI` | `./artifacts/logs/actions.jsonl` | the agent's action log |
| `API_URL` | `http://127.0.0.1:8000` | the agent API the screen calls |
| `SOURCE` | `mock` | `mock` or `model` |
| `SCENARIO` | `A` | station for `SOURCE=model` |
| `MODEL_VERSION` | `safe-cap-qgb-v1` | which saved model is loaded |
| `EVAL_RUN_ID` | `local` | which evaluation the screen shows |
| `DEMO_TOKEN` | unset | when set, required for write actions |
| `EUENERGY_TOKEN` | unset | `python -m src.pricing.prices fetch` |

### Windows (PowerShell)
Activate with `.venv\Scripts\Activate.ps1`, and set variables before the command, for example `$env:API_URL = "http://127.0.0.1:8000"`.

## Data and sources
| Source | Use | Licence |
|---|---|---|
| Ausgrid "Solar home electricity data" (300 homes, Sydney, 2010–2013), [copy by Pierre Haessig](https://pierreh.eu/ausgrid-solar-data/) | household consumption and solar generation | CC BY 3.0 AU (as stated in the copy) |
| [SimBench](https://github.com/e2nIEE/simbench) and [pandapower](https://github.com/e2nIEE/pandapower) | grid benchmark and power flow | see the projects |
| Labels | the highest safe export share, computed by our power flow (synthetic) | ours |
| [euenergy.live](https://euenergy.live) hourly Romanian day-ahead prices | price comparison | CC BY 4.0, credit euenergy.live |

Details and pitfalls: [src/ml/DATA.md](src/ml/DATA.md) and [docs/05-data-and-sources.md](docs/05-data-and-sources.md). The rest of the documentation is in [docs/](docs/).

## Keeping this README current
Every change that affects how the project runs updates this README in the same pull request. That includes a new or changed command, option, environment variable, dependency, data step, port, output path or expected time. The reviewer checks it before approving.
