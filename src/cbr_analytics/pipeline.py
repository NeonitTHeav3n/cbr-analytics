"""Оркестрация пайплайна: extract -> load raw -> SQL-витрины -> проверки -> отчёт."""

from __future__ import annotations

from pathlib import Path

from cbr_analytics.config import Config
from cbr_analytics.extract.currency import extract_currency
from cbr_analytics.extract.key_rate import extract_key_rate
from cbr_analytics.http import get_logger
from cbr_analytics.load.warehouse import Warehouse
from cbr_analytics.transform.clean import clean_currency, clean_key_rate
from cbr_analytics.transform.quality import (
    check_currency_frame,
    check_key_rate_frame,
    enforce,
    run_mart_checks,
)

log = get_logger(__name__)
SQL_DIR = Path(__file__).resolve().parents[2] / "sql"


def run_extract(cfg: Config, *, force: bool = False) -> tuple:
    log.info("=== EXTRACT: %s .. %s", cfg.start_date, cfg.end_date)
    currency = extract_currency(cfg.extract, cfg.start_date, cfg.end_date, cfg.raw_dir, force=force)
    key_rate = extract_key_rate(cfg.extract, cfg.start_date, cfg.end_date, cfg.raw_dir, force=force)

    currency = clean_currency(currency, cfg.start_date, cfg.end_date)
    key_rate = clean_key_rate(key_rate, cfg.start_date, cfg.end_date)

    enforce(check_currency_frame(currency) + check_key_rate_frame(key_rate))
    return currency, key_rate


def sql_params(cfg: Config) -> dict[str, object]:
    return {
        "vol_window_minus_one": cfg.transform.volatility_window_days - 1,
        "horizons_values": ",".join(f"({d})" for d in cfg.transform.horizons_days),
        "forecast_horizon": cfg.transform.forecast_horizon_days,
        "annualization_days": cfg.transform.annualization_days,
    }


def run_build(cfg: Config, data: tuple) -> Warehouse:
    """Грузит сырые данные в staging и собирает витрины SQL-ом."""
    currency, key_rate = data
    log.info("=== LOAD + TRANSFORM (engine=%s)", cfg.load.engine)
    warehouse = Warehouse(cfg.load)
    warehouse.connect()
    warehouse.load_dataframe(currency, "raw_currency_rates")
    warehouse.load_dataframe(key_rate, "raw_key_rate")
    warehouse.run_sql_dir(SQL_DIR, sql_params(cfg))

    log.info("=== CHECKS")
    enforce(run_mart_checks(warehouse.query))
    return warehouse


def run_all(cfg: Config, *, force: bool = False) -> Warehouse:
    data = run_extract(cfg, force=force)
    return run_build(cfg, data)
