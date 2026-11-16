"""Интеграционный тест: весь SQL-пайплайн на DuckDB с детерминированными данными.

Это самый ценный тест в проекте: если кто-то сломает витрину, CI это покажет
без похода в интернет и без скачивания данных ЦБ.
"""

from __future__ import annotations

import datetime as dt
import math

import pandas as pd
import pytest

from cbr_analytics.config import LoadConfig
from cbr_analytics.load.warehouse import Warehouse
from cbr_analytics.pipeline import SQL_DIR

START = dt.date(2020, 1, 1)
DAYS = 800
KEY_RATE = 10.0  # постоянная ставка: тогда доходность вклада считается аналитически


def business_days(start: dt.date, count: int) -> list[dt.date]:
    days, cursor = [], start
    while len(days) < count:
        if cursor.weekday() < 5:  # ЦБ не публикует курс по выходным
            days.append(cursor)
        cursor += dt.timedelta(days=1)
    return days


@pytest.fixture(scope="module")
def warehouse(tmp_path_factory) -> Warehouse:
    db_path = tmp_path_factory.mktemp("db") / "test.duckdb"
    wh = Warehouse(LoadConfig(engine="duckdb", duckdb_path=str(db_path)))
    wh.connect()

    dates = business_days(START, DAYS)
    # USD растёт линейно 60 -> 75, EUR стоит на месте: удобно проверять знак diff
    usd = pd.DataFrame(
        {
            "rate_date": dates,
            "char_code": "USD",
            "nominal": 1,
            "rate_per_unit": [60.0 + 15.0 * i / (DAYS - 1) for i in range(DAYS)],
        }
    )
    eur = pd.DataFrame(
        {
            "rate_date": dates,
            "char_code": "EUR",
            "nominal": 1,
            "rate_per_unit": [70.0] * DAYS,
        }
    )
    key = pd.DataFrame({"rate_date": dates, "key_rate_pct": [KEY_RATE] * DAYS})

    wh.load_dataframe(pd.concat([usd, eur], ignore_index=True), "raw_currency_rates")
    wh.load_dataframe(key, "raw_key_rate")
    wh.run_sql_dir(
        SQL_DIR,
        {
            "vol_window_minus_one": 29,
            "horizons_values": "(30),(365)",
            "forecast_horizon": 30,
            "annualization_days": 252,
        },
    )
    yield wh
    wh.close()


def test_marts_are_created(warehouse):
    tables = {
        row[0]
        for row in warehouse.query(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).itertuples(index=False)
    }
    expected = {
        "stg_currency_rates",
        "stg_key_rate",
        "int_calendar",
        "int_currency_daily",
        "int_key_rate_daily",
        "int_deposit_index",
        "int_fx_returns",
        "mart_fx_monthly",
        "mart_volatility",
        "mart_deposit_vs_fx",
        "mart_headline",
        "mart_monthly_index",
        "mart_forecast_band",
    }
    assert expected <= tables


def test_calendar_is_continuous(warehouse):
    gaps = warehouse.query(
        """
        SELECT COUNT(*) AS gaps FROM (
            SELECT calendar_date,
                   calendar_date - LAG(calendar_date) OVER (ORDER BY calendar_date) AS diff
            FROM int_calendar
        ) WHERE diff > 1
        """
    ).iloc[0, 0]
    assert gaps == 0


def test_weekend_rates_are_forward_filled(warehouse):
    """Курс на субботу = курс пятницы, иначе горизонты 30/90/365 «съезжают»."""
    df = warehouse.query(
        """
        SELECT rate_date, rub_per_unit,
               dayofweek(rate_date) AS dow,
               LAG(rub_per_unit) OVER (PARTITION BY char_code ORDER BY rate_date) AS prev
        FROM int_currency_daily
        WHERE char_code = 'USD'
        """
    )
    weekends = df[df.dow.isin([0, 6])]
    assert len(weekends) > 0
    assert (weekends.rub_per_unit == weekends.prev).all()


def test_deposit_index_matches_compounding(warehouse):
    """За год при ставке 10% индекс должен дать (1 + 0.1/365)^365 ≈ 10.52%."""
    row = warehouse.query(
        """
        SELECT d2.deposit_index / d1.deposit_index - 1 AS growth
        FROM int_deposit_index d1
        JOIN int_deposit_index d2 ON d2.calendar_date = d1.calendar_date + 365
        WHERE d1.calendar_date = DATE '2020-01-01'
        """
    ).iloc[0, 0]

    assert row == pytest.approx(math.exp(KEY_RATE / 100) - 1, rel=1e-3)


def test_deposit_vs_fx_math(warehouse):
    df = warehouse.query(
        """
        SELECT * FROM mart_deposit_vs_fx
        WHERE char_code = 'USD' AND horizon_days = 365
        ORDER BY start_date LIMIT 1
        """
    ).iloc[0]

    assert df.fx_return == pytest.approx(df.fx_end / df.fx_start - 1)
    assert df.diff_pp == pytest.approx(df.deposit_return - df.fx_return)
    assert df.deposit_return == pytest.approx(math.exp(KEY_RATE / 100) - 1, rel=1e-3)


def test_deposit_beats_flat_currency(warehouse):
    """EUR не менялся, ставка 10% -> вклад обязан выигрывать всегда."""
    share = warehouse.query(
        "SELECT deposit_win_share FROM mart_headline WHERE char_code = 'EUR' AND horizon_days = 365"
    ).iloc[0, 0]
    assert share == 1.0


def test_volatility_of_flat_series_is_zero(warehouse):
    vol = warehouse.query(
        "SELECT MAX(vol_annualized) FROM mart_volatility WHERE char_code = 'EUR'"
    ).iloc[0, 0]
    assert vol == pytest.approx(0.0, abs=1e-9)


def test_forecast_band_brackets_spot(warehouse):
    band = warehouse.query("SELECT * FROM mart_forecast_band")
    assert len(band) == 2
    assert (band.band_low_95 <= band.spot).all()
    assert (band.band_high_95 >= band.spot).all()


def test_render_sql_rejects_unfilled_placeholders(warehouse):
    with pytest.raises(ValueError, match="placeholder"):
        warehouse.render_sql("SELECT {{missing_param}}", {"other": 1})


def test_render_sql_substitutes_values(warehouse):
    sql = warehouse.render_sql("SELECT {{horizons_values}}", {"horizons_values": "(30),(90)"})
    assert sql == "SELECT (30),(90)"
