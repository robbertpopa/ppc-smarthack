PY ?= $(shell test -x .venv/bin/python && echo .venv/bin/python || echo python3)
COMPOSE = docker compose -f infra/docker-compose.yml
TF_DIR = infra/terraform
TF ?= terraform

.PHONY: setup smoke test lint run docker-build up down docker-test batch tf-fmt tf-validate tf-init tf-plan tf-apply

setup:
	$(PY) -m pip install -e ".[dev,ml,sim]"

smoke:
	$(PY) -m src.smoke

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src tests

run:
	$(PY) -m uvicorn src.agent.api:app --reload --port 8000

docker-build:
	$(COMPOSE) build

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down

docker-test:
	$(COMPOSE) --profile test run --rm test
	$(COMPOSE) --profile test run --rm lint

batch:
	$(COMPOSE) --profile batch run --rm batch $(CMD)

tf-fmt:
	$(TF) -chdir=$(TF_DIR) fmt -recursive

tf-validate:
	$(TF) -chdir=$(TF_DIR) init -backend=false -input=false
	$(TF) -chdir=$(TF_DIR) validate

tf-init:
	$(TF) -chdir=$(TF_DIR) init -backend-config=backend.hcl

tf-plan:
	$(TF) -chdir=$(TF_DIR) plan

tf-apply:
	$(TF) -chdir=$(TF_DIR) apply

.PHONY: replay
replay:
	$(PY) -m src.agent.replay --date $(DATE) $(ARGS)
