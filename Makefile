VENV := .venv
ifeq ($(OS),Windows_NT)
PY := $(VENV)/Scripts/python.exe
else
PY := $(VENV)/bin/python
endif

.PHONY: setup data warehouse geo eda model test deck app all \
	web-export web-install web-build web-dev all-web

setup:
	python -m venv $(VENV)
	$(PY) -m pip install -r requirements.txt

data:
	$(PY) etl/download.py

warehouse:
	$(PY) etl/parse.py --allow-anomalies

geo:
	$(PY) etl/geo.py

eda:
	$(PY) analysis/eda.py

model:
	$(PY) analysis/model.py

test:
	$(PY) -m pytest -q

deck:
	$(PY) presentation/build_deck.py

app:
	$(PY) -m streamlit run app/app.py

web-export:
	$(PY) export/export_web.py

web-install:
	cd app/web && npm install

web-build: web-export
	cd app/web && npm run build

web-dev:
	cd app/web && npm run dev

all: data warehouse geo eda model test deck

all-web: all web-build
