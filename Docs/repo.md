# Kronos — Repository Reconstruction Plan

> **Prepared by:** Repo Architect Review  
> **Scope:** Full structural refactor for scalability, deployability, and maintainability  
> **Target:** Production-grade monorepo with independently deployable services

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Problems Identified](#2-problems-identified)
3. [Target Directory Structure](#3-target-directory-structure)
4. [Key Architectural Decisions](#4-key-architectural-decisions)
5. [Migration Steps](#5-migration-steps-in-order)
6. [Deployment Architecture](#6-deployment-architecture)
7. [Configuration Strategy](#7-configuration-strategy)
8. [Testing Strategy](#8-testing-strategy)
9. [What Gets Deleted](#9-what-gets-deleted)
10. [File-by-File Mapping](#10-file-by-file-mapping)

---

## 1. Current State Analysis

The current repo has the following surface-level component groups:

| Group | Files |
|---|---|
| Core ML Model | `model/kronos.py`, `model/module.py` |
| Training Pipeline A | `finetune/` (qlib-based) |
| Training Pipeline B | `finetune_csv/` (CSV-based) |
| Signal Generation | `signal_generator.py` |
| Strategy | `strategist.py`, `objective_tracker.py` |
| Broker Integration | `broker_api.py` |
| Live Trading | `trader_daemon.py` |
| Backtesting | `backtester.py` |
| Data Ingestion | `data_fetcher.py` |
| Database | `database.py` |
| Research / Agent | `research_node.py`, `skills_engine.py` |
| UI A | `dashboard.py` |
| UI B | `webui/` (Flask app with templates) |
| Data Storage | `data/` (CSVs + SQLite DB mixed) |
| Examples | `examples/` (production-adjacent scripts) |
| Tests | `tests/` (single regression test) |
| Deployment | `kronos.service`, `setup.sh` |

---

## 2. Problems Identified

### 2.1 Flat Root
Over 10 Python modules live at the repo root with no domain boundary. Any new developer cannot determine what is a service entrypoint vs. a library module vs. a utility script.

### 2.2 Duplicate UIs
`dashboard.py` and `webui/` serve overlapping purposes. Two UIs means two places to maintain templates, two sets of routes, and two mental models. The webui Flask app is clearly more complete; `dashboard.py` is a dead-end.

### 2.3 Duplicate Training Pipelines
`finetune/` (qlib-based) and `finetune_csv/` (CSV-based) implement similar functionality with diverging code. Every bug fix must be applied twice. These must be unified under a single pipeline controlled by configuration.

### 2.4 No Broker Abstraction
`broker_api.py` is a single monolithic file. Adding a second broker (Zerodha, IBKR, Binance) requires modifying existing production code — a direct violation of the Open/Closed Principle.

### 2.5 Data and DB Mixed
Raw CSVs and `kronos_broker.db` (SQLite) sit in the same `data/` folder. CSVs are local dev cache and should not be in version control. The DB is a runtime artifact and should not be in the same directory as raw data inputs.

### 2.6 No Config Layer
No centralized configuration management. Paths, credentials, and parameters are likely hardcoded or scattered. This blocks environment-based deployment (dev / staging / prod).

### 2.7 Non-installable Package
The codebase is not a proper Python package. Scripts use relative imports or `sys.path` hacks. This makes it impossible to deploy individual services (daemon, API, UI) as separate containers without bundling the entire repo.

### 2.8 Minimal Tests
One regression test file for a multi-module, money-moving system. No unit tests, no integration tests, no CI configuration.

### 2.9 Examples in Production Space
`examples/` contains scripts that reference production code but are not themselves production code. They are co-located with the main codebase, creating confusion about what is "live."

---

## 3. Target Directory Structure

```
kronos/
├── README.md
├── LICENSE
├── pyproject.toml                  # replaces requirements.txt; makes kronos pip-installable
├── Makefile                        # dev shortcuts: make train, make backtest, make serve
├── .env.example                    # template for secrets (never commit .env)
├── .gitignore
│
├── config/                         # ALL configuration; no hardcoded values anywhere in src
│   ├── default.yaml                # base config valid for all environments
│   ├── dev.yaml                    # overrides for local development
│   ├── prod.yaml                   # overrides for production
│   ├── broker.yaml.example         # broker credentials template (gitignored with actuals)
│   └── logging.yaml
│
├── kronos/                         # installable Python package (pip install -e .)
│   ├── __init__.py
│   ├── config.py                   # config loader: reads YAML + env vars, typed dataclass
│   │
│   ├── model/                      # Core ML — pure functions, no I/O, no side effects
│   │   ├── __init__.py
│   │   ├── kronos.py
│   │   └── module.py
│   │
│   ├── data/                       # Data access layer
│   │   ├── __init__.py
│   │   ├── fetcher.py              # was data_fetcher.py
│   │   ├── repository.py           # was database.py — DB access object (not raw SQL)
│   │   └── schema.py               # table/model definitions (SQLAlchemy or dataclasses)
│   │
│   ├── training/                   # Unified fine-tune pipeline
│   │   ├── __init__.py
│   │   ├── config.py               # TrainingConfig dataclass
│   │   ├── dataset.py              # merged from finetune/ + finetune_csv/
│   │   ├── trainer.py              # single entry point, source-agnostic
│   │   ├── tokenizer.py
│   │   └── utils.py
│   │
│   ├── signals/
│   │   ├── __init__.py
│   │   └── generator.py            # was signal_generator.py
│   │
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── strategist.py
│   │   └── objective_tracker.py
│   │
│   ├── broker/
│   │   ├── __init__.py
│   │   ├── base.py                 # abstract Broker interface (place_order, get_positions, etc.)
│   │   └── fyers.py                # was broker_api.py — implements base.Broker
│   │
│   ├── backtester/
│   │   ├── __init__.py
│   │   └── engine.py               # was backtester.py
│   │
│   ├── research/
│   │   ├── __init__.py
│   │   ├── node.py                 # was research_node.py
│   │   └── skills.py               # was skills_engine.py
│   │
│   └── daemon/
│       ├── __init__.py
│       └── trader.py               # was trader_daemon.py
│
├── api/                            # HTTP service — independently deployable
│   ├── __init__.py
│   ├── main.py                     # FastAPI app; mounts all routers
│   ├── routers/
│   │   ├── predictions.py
│   │   ├── backtests.py
│   │   └── health.py
│   ├── requirements.txt            # api-specific deps only
│   └── Dockerfile
│
├── ui/                             # Single consolidated UI — independently deployable
│   ├── app.py                      # was webui/app.py (winner over dashboard.py)
│   ├── run.py
│   ├── templates/
│   │   ├── index.html
│   │   └── dashboard.html
│   ├── requirements.txt
│   ├── start.sh
│   └── Dockerfile
│
├── scripts/                        # Ops / one-off tooling; never imported by src
│   ├── fetch_data.py
│   ├── run_backtest.py
│   └── generate_regression_output.py
│
├── tests/
│   ├── conftest.py                 # shared fixtures (model load, mock broker, etc.)
│   ├── unit/
│   │   ├── test_model.py
│   │   ├── test_signals.py
│   │   ├── test_strategy.py
│   │   └── test_backtester.py
│   ├── integration/
│   │   ├── test_broker_fyers.py    # requires live or sandbox credentials
│   │   └── test_data_fetcher.py
│   └── regression/
│       ├── data/
│       │   ├── regression_input.csv
│       │   └── regression_output_512.csv
│       └── test_kronos_regression.py
│
├── storage/                        # Runtime artifacts — fully gitignored
│   └── .gitkeep
│
├── deploy/
│   ├── docker-compose.yaml         # local multi-service stack
│   ├── kronos.service              # systemd unit for bare-metal
│   └── k8s/                        # Kubernetes manifests (scale-out path)
│       ├── api-deployment.yaml
│       ├── ui-deployment.yaml
│       ├── daemon-deployment.yaml
│       └── configmap.yaml
│
└── notebooks/                      # was examples/ — clearly non-production
    ├── prediction_example.ipynb
    ├── backtest_walkthrough.ipynb
    └── cn_markets_analysis.ipynb
```

---

## 4. Key Architectural Decisions

### 4.1 Installable Package (`pyproject.toml`)

Convert the repo into a proper Python package. Every service (`api/`, `ui/`, daemon entrypoint) imports from `kronos.*` using absolute imports.

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "kronos"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "torch",
    "pandas",
    "sqlalchemy",
    "pyyaml",
    "fastapi",
    "uvicorn",
]

[project.optional-dependencies]
training = ["qlib", "transformers", "accelerate"]
broker-fyers = ["fyers-apiv3"]
dev = ["pytest", "ruff", "mypy"]
```

**Why:** Eliminates all `sys.path` hacks. Enables per-service Docker images that install only what they need via extras.

---

### 4.2 Broker Abstraction Layer

Define a strict interface in `kronos/broker/base.py`:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class Order:
    symbol: str
    qty: float
    side: str          # "BUY" | "SELL"
    order_type: str    # "MARKET" | "LIMIT"
    price: float | None = None

class Broker(ABC):
    @abstractmethod
    def place_order(self, order: Order) -> str: ...      # returns order_id

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool: ...

    @abstractmethod
    def get_positions(self) -> list[dict]: ...

    @abstractmethod
    def get_balance(self) -> float: ...
```

`kronos/broker/fyers.py` implements `Broker`. Adding Zerodha tomorrow is zero-risk — it gets its own file, existing code is untouched.

---

### 4.3 Unified Training Pipeline

The discriminator between qlib and CSV inputs becomes a config value, not two separate directories.

```yaml
# config/training/csv_run.yaml
training:
  source: csv
  data_path: storage/raw/BINANCE_BTCUSDT_1h_90d.csv
  epochs: 50
  batch_size: 32

# config/training/qlib_run.yaml
training:
  source: qlib
  qlib_data_path: ~/.qlib/qlib_data/cn_data
  epochs: 50
  batch_size: 32
```

`kronos/training/trainer.py` reads `source` and delegates to the appropriate dataset loader. One codebase, two inputs.

---

### 4.4 Single UI (`ui/`)

`webui/` wins. It has templates, a proper app structure, and prediction result storage. `dashboard.py` is retired. The UI gets its own `Dockerfile` and can be deployed to a separate container or served via CDN + Flask/Gunicorn.

---

### 4.5 Data Strategy

| Data Type | Current Location | Target Location | In Git? |
|---|---|---|---|
| Raw CSVs (dev cache) | `data/*.csv` | `storage/raw/` | **No** (`.gitignore`) |
| SQLite DB (local dev) | `data/kronos_broker.db` | `storage/kronos.db` | **No** |
| Regression test fixtures | `tests/data/` | `tests/regression/data/` | **Yes** (small, versioned) |
| Prediction results | `webui/prediction_results/` | `storage/predictions/` | **No** |

In production, `repository.py` reads `DATABASE_URL` from the environment and connects to Postgres/TimescaleDB. SQLite is only used locally when `DATABASE_URL` is unset.

---

### 4.6 Configuration Hierarchy

```
config/default.yaml         ← always loaded
config/{ENV}.yaml           ← loaded if ENV=dev|prod|staging
.env                        ← secrets only (never committed)
Environment variables       ← highest priority, always win
```

The loader in `kronos/config.py` merges these in order, returning a typed `KronosConfig` dataclass. No module outside `kronos/config.py` reads environment variables directly.

---

## 5. Migration Steps (In Order)

Execute these in sequence. Each step leaves the system in a working state.

### Step 1 — Create the package skeleton
```bash
mkdir -p kronos/{model,data,training,signals,strategy,broker,backtester,research,daemon}
touch kronos/__init__.py
touch kronos/{model,data,training,signals,strategy,broker,backtester,research,daemon}/__init__.py
```

### Step 2 — Move and rename root modules
```bash
# Exact moves; fix imports after each one
mv model/kronos.py     kronos/model/kronos.py
mv model/module.py     kronos/model/module.py
mv data_fetcher.py     kronos/data/fetcher.py
mv database.py         kronos/data/repository.py
mv signal_generator.py kronos/signals/generator.py
mv strategist.py       kronos/strategy/strategist.py
mv objective_tracker.py kronos/strategy/objective_tracker.py
mv broker_api.py       kronos/broker/fyers.py
mv backtester.py       kronos/backtester/engine.py
mv research_node.py    kronos/research/node.py
mv skills_engine.py    kronos/research/skills.py
mv trader_daemon.py    kronos/daemon/trader.py
```

### Step 3 — Create broker abstraction
Create `kronos/broker/base.py` with the abstract `Broker` class. Refactor `kronos/broker/fyers.py` to inherit from it.

### Step 4 — Merge training pipelines
- Create `kronos/training/trainer.py`  
- Port `finetune/dataset.py` → `kronos/training/dataset.py` with CSV and qlib branches  
- Port `finetune/train_predictor.py` and `finetune_csv/finetune_base_model.py` → `kronos/training/trainer.py`  
- Delete `finetune/` and `finetune_csv/` directories

### Step 5 — Consolidate UI
- Move `webui/app.py` → `ui/app.py`  
- Move `webui/templates/` → `ui/templates/`  
- Move `webui/run.py` → `ui/run.py`  
- Delete `dashboard.py` and `webui/`

### Step 6 — Set up config layer
- Create `kronos/config.py` with YAML + env var loader  
- Create `config/default.yaml`, `config/dev.yaml`, `config/prod.yaml`  
- Create `.env.example`  
- Add `.env`, `config/broker.yaml`, `storage/` to `.gitignore`

### Step 7 — Migrate data
```bash
mkdir -p storage/raw storage/predictions
# Move CSVs out of git
mv data/*.csv storage/raw/
mv data/kronos_broker.db storage/kronos.db
# Update .gitignore to exclude storage/
echo "storage/" >> .gitignore
echo "!storage/.gitkeep" >> .gitignore
```

### Step 8 — Write `pyproject.toml`
Replace `requirements.txt` with `pyproject.toml`. Run `pip install -e ".[dev]"` locally to verify.

### Step 9 — Expand test coverage
- Write `tests/conftest.py` with shared fixtures  
- Write unit tests for `model`, `signals`, `strategy`  
- Move `tests/data/` → `tests/regression/data/`  
- Move regression test to `tests/regression/`

### Step 10 — Write Dockerfiles and compose
- `api/Dockerfile`  
- `ui/Dockerfile`  
- `deploy/docker-compose.yaml`  
- Verify `docker compose up` brings all three services online

### Step 11 — Move examples to notebooks
```bash
mkdir notebooks
# Convert .py examples to .ipynb or leave as .py under notebooks/
mv examples/* notebooks/
rmdir examples/
```

### Step 12 — CI/CD (GitHub Actions recommended)
Create `.github/workflows/ci.yaml`:
- On every PR: `ruff check`, `mypy`, `pytest tests/unit/`
- On merge to main: `pytest tests/` + build Docker images

---

## 6. Deployment Architecture

### Local Development
```bash
# One command to start everything
docker compose -f deploy/docker-compose.yaml up
```

### `deploy/docker-compose.yaml` (outline)
```yaml
services:
  api:
    build: ./api
    ports: ["8000:8000"]
    env_file: .env
    volumes:
      - ./storage:/app/storage

  ui:
    build: ./ui
    ports: ["5000:5000"]
    depends_on: [api]

  daemon:
    build:
      context: .
      dockerfile: deploy/Dockerfile.daemon
    env_file: .env
    volumes:
      - ./storage:/app/storage
    restart: unless-stopped
```

### Bare Metal (existing systemd path)
`deploy/kronos.service` targets the daemon only. API and UI run under separate service units or nginx proxy.

### Scale-Out (Kubernetes)
`deploy/k8s/` provides Deployment and Service manifests for each component. The daemon runs as a single-replica Deployment with `restartPolicy: Always`. API scales horizontally behind a LoadBalancer Service.

---

## 7. Configuration Strategy

### Config loading order (highest priority last wins)
1. `config/default.yaml`
2. `config/{APP_ENV}.yaml` (e.g. `APP_ENV=prod`)
3. `.env` file
4. Shell environment variables

### `kronos/config.py` (skeleton)
```python
import os
import yaml
from dataclasses import dataclass, field

@dataclass
class DatabaseConfig:
    url: str = "sqlite:///storage/kronos.db"

@dataclass
class BrokerConfig:
    name: str = "fyers"
    client_id: str = ""
    secret: str = ""

@dataclass
class KronosConfig:
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    model_path: str = "storage/models/kronos_latest.pt"

def load_config() -> KronosConfig:
    env = os.getenv("APP_ENV", "dev")
    # Load and merge YAMLs, overlay env vars, return typed config
    ...
```

No module outside `config.py` calls `os.getenv`. Secrets never appear in logs.

---

## 8. Testing Strategy

### Unit Tests (`tests/unit/`)
- Pure function tests; no network, no disk, no broker
- Mock `Broker` base class for strategy tests
- Target: **>80% coverage** on `kronos/model`, `kronos/signals`, `kronos/strategy`

### Integration Tests (`tests/integration/`)
- Requires real or sandbox broker credentials
- Skipped in CI unless `RUN_INTEGRATION=1` env var is set
- Tests actual Fyers API calls with minimal position sizes

### Regression Tests (`tests/regression/`)
- Existing `test_kronos_regression.py` migrated here
- Fixtures versioned in `tests/regression/data/`
- Run on every commit; output must be deterministic

### CI Configuration (`.github/workflows/ci.yaml`)
```yaml
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[dev]"
      - run: ruff check kronos/
      - run: mypy kronos/
      - run: pytest tests/unit/ tests/regression/ -v
```

---

## 9. What Gets Deleted

| Path | Reason |
|---|---|
| `dashboard.py` | Superseded by `ui/` (webui) |
| `finetune/` | Merged into `kronos/training/` |
| `finetune_csv/` | Merged into `kronos/training/` |
| `webui/` | Moved to `ui/` |
| `examples/` | Moved to `notebooks/` |
| `data/*.csv` | Runtime cache; added to `.gitignore` |
| `data/kronos_broker.db` | Runtime artifact; moved to `storage/` |
| `fyersApi.log` | Runtime log; added to `.gitignore` |
| `fyersRequests.log` | Runtime log; added to `.gitignore` |
| `setup.sh` | Replaced by `Makefile` + `pyproject.toml` |
| `skills-lock.json` | Clarify purpose; if a lockfile, regenerate from config |
| `model/` (root-level dir) | Moved to `kronos/model/` |

---

## 10. File-by-File Mapping

| Original Path | New Path | Action |
|---|---|---|
| `model/kronos.py` | `kronos/model/kronos.py` | Move |
| `model/module.py` | `kronos/model/module.py` | Move |
| `data_fetcher.py` | `kronos/data/fetcher.py` | Move + rename |
| `database.py` | `kronos/data/repository.py` | Move + rename |
| `signal_generator.py` | `kronos/signals/generator.py` | Move + rename |
| `strategist.py` | `kronos/strategy/strategist.py` | Move |
| `objective_tracker.py` | `kronos/strategy/objective_tracker.py` | Move |
| `broker_api.py` | `kronos/broker/fyers.py` | Move + rename + refactor |
| `backtester.py` | `kronos/backtester/engine.py` | Move + rename |
| `research_node.py` | `kronos/research/node.py` | Move + rename |
| `skills_engine.py` | `kronos/research/skills.py` | Move + rename |
| `trader_daemon.py` | `kronos/daemon/trader.py` | Move + rename |
| `finetune/*.py` | `kronos/training/*.py` | Merge |
| `finetune_csv/*.py` | `kronos/training/*.py` | Merge |
| `dashboard.py` | *(deleted)* | Superseded |
| `webui/app.py` | `ui/app.py` | Move |
| `webui/templates/` | `ui/templates/` | Move |
| `webui/run.py` | `ui/run.py` | Move |
| `webui/requirements.txt` | `ui/requirements.txt` | Move |
| `webui/prediction_results/` | `storage/predictions/` | Move + gitignore |
| `examples/*.py` | `notebooks/` | Move + convert |
| `tests/test_kronos_regression.py` | `tests/regression/test_kronos_regression.py` | Move |
| `tests/data/` | `tests/regression/data/` | Move |
| `data/*.csv` | `storage/raw/` | Move + gitignore |
| `data/kronos_broker.db` | `storage/kronos.db` | Move + gitignore |
| `kronos.service` | `deploy/kronos.service` | Move |
| `requirements.txt` | `pyproject.toml` | Replace |
| `setup.sh` | `Makefile` | Replace |

---

*End of Reconstruction Plan*