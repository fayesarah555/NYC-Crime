VENV := .venv
ifeq ($(OS),Windows_NT)
PY := $(VENV)/Scripts/python.exe
else
PY := $(VENV)/bin/python
endif

.DELETE_ON_ERROR:
.DEFAULT_GOAL := help

.PHONY: help setup data data-verify warehouse geo eda model test check clean \
	readme-check \
	deck app all web-export web-install web-build web-dev e2e all-web

help:
	@echo "NYC park crime — available targets:"
	@echo "  make setup       create .venv and install Python deps (>= 3.11)"
	@echo "  make data        download the NYPD park-crime workbooks"
	@echo "  make data-verify verify downloads against data/manifest.lock.json"
	@echo "  make warehouse   parse workbooks into the SQLite warehouse"
	@echo "  make geo         join NYC Parks coordinates"
	@echo "  make eda         exploratory figures, tables and stats"
	@echo "  make model       forecast, clustering and risk table"
	@echo "  make test        pytest with coverage gate"
	@echo "  make check       ruff + mypy + tests"
	@echo "  make deck        rebuild the PowerPoint deck"
	@echo "  make app         run the Streamlit analyst view"
	@echo "  make web-install install the dashboard dependencies"
	@echo "  make web-build   export JSON and build the static dashboard"
	@echo "  make e2e         Playwright smoke tests against the built site"
	@echo "  make all         data -> warehouse -> geo -> eda -> model -> test -> deck"
	@echo "  make all-web     all + web-build"
	@echo "  make clean       remove generated data, outputs, dist and caches"

setup:
	@python -c "import sys; assert sys.version_info >= (3, 11), 'Python >= 3.11 required'"
	python -m venv $(VENV)
	$(PY) -m pip install -e ".[dev]"

data:
	$(PY) etl/download.py --allow-missing

data-verify:
	$(PY) etl/download.py --verify-lock

warehouse:
	$(PY) etl/parse.py --allow-anomalies

geo:
	$(PY) etl/geo.py

eda:
	$(PY) analysis/eda.py

model:
	$(PY) analysis/model.py

test:
	$(PY) -m pytest -q --cov --cov-report=term-missing

check:
	$(PY) -m ruff check .
	$(PY) -m mypy etl analysis export
	$(PY) -m pytest -q --cov --cov-report=term-missing
	$(PY) scripts/check_readme_numbers.py

readme-check:
	$(PY) scripts/check_readme_numbers.py

clean:
	rm -rf data/processed data/warehouse.db app/web/dist app/web/coverage \
		app/web/test-results .pytest_cache .coverage htmlcov
	$(PY) -m pip cache purge >/dev/null 2>&1 || true

deck:
	$(PY) presentation/build_deck.py

app:
	$(PY) -m streamlit run app/app.py

web-export:
	$(PY) export/export_web.py

web-install:
	cd app/web && npm ci

web-build: web-export
	@test -d app/web/node_modules || $(MAKE) web-install
	cd app/web && npm run build

web-dev:
	cd app/web && npm run dev

e2e: web-build
	cd app/web && npm run e2e

all: data warehouse geo eda model test deck

all-web: all web-build
