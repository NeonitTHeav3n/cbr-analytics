.DEFAULT_GOAL := help
PY ?= python3
# работает и без `make install`: CLI подхватывается прямо из src/
export PYTHONPATH := src

.PHONY: help install extract build report all test lint up down clean clean-raw

help:  ## показать список команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## поставить зависимости (с dev-инструментами)
	$(PY) -m pip install -e ".[dev]"

extract:  ## скачать сырые данные ЦБ в data/raw (кэшируется)
	$(PY) -m cbr_analytics extract

build:  ## собрать витрины в DuckDB из скачанных данных
	$(PY) -m cbr_analytics build

report:  ## пересобрать docs/dashboard.html и docs/dashboard.png
	$(PY) -m cbr_analytics report

all:  ## полный прогон: extract -> витрины -> проверки -> дашборд
	$(PY) -m cbr_analytics all

test:  ## тесты (без сети)
	$(PY) -m pytest

lint:  ## линтер
	$(PY) -m ruff check .

up:  ## поднять Postgres + Metabase (для BI-варианта)
	docker compose up -d

down:  ## остановить контейнеры
	docker compose down

clean-raw:  ## удалить скачанные данные (принудительная перезагрузка при следующем extract)
	rm -rf data/raw data/cbr.duckdb

clean: clean-raw  ## удалить данные и кэши
	rm -rf .pytest_cache .ruff_cache **/__pycache__
