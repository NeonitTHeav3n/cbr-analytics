"""Тесты очистки и проверок качества."""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from cbr_analytics.transform.clean import clean_currency, clean_key_rate
from cbr_analytics.transform.quality import (
    QualityError,
    check_currency_frame,
    check_key_rate_frame,
    enforce,
)


def make_currency_frame(dates, values, code="USD") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "rate_date": dates,
            "char_code": [code] * len(dates),
            "nominal": [1] * len(dates),
            "rate_per_unit": values,
        }
    )


def test_clean_currency_filters_out_of_range_dates():
    df = make_currency_frame(
        [dt.date(2019, 12, 31), dt.date(2020, 1, 10), dt.date(2020, 2, 1)],
        [61.0, 61.5, 63.0],
    )

    out = clean_currency(df, dt.date(2020, 1, 1), dt.date(2020, 1, 31))

    assert len(out) == 1
    assert out.iloc[0]["rate_date"] == dt.date(2020, 1, 10)


def test_clean_currency_drops_non_positive_and_duplicates():
    df = make_currency_frame(
        [dt.date(2020, 1, 10), dt.date(2020, 1, 10), dt.date(2020, 1, 11)],
        [61.0, 62.0, 0.0],  # дубль по дате + нулевой курс
    )

    out = clean_currency(df, dt.date(2020, 1, 1), dt.date(2020, 1, 31))

    assert len(out) == 1
    assert out.iloc[0]["rate_per_unit"] == 62.0  # из дублей остаётся последний


def test_clean_key_rate_sorts_and_dedups():
    df = pd.DataFrame(
        {
            "rate_date": [dt.date(2020, 1, 3), dt.date(2020, 1, 2), dt.date(2020, 1, 3)],
            "key_rate_pct": [7.0, 6.25, 6.25],
        }
    )

    out = clean_key_rate(df, dt.date(2020, 1, 1), dt.date(2020, 1, 31))

    assert len(out) == 2
    assert list(out["rate_date"]) == [dt.date(2020, 1, 2), dt.date(2020, 1, 3)]


def test_quality_flags_negative_rate():
    df = make_currency_frame([dt.date(2020, 1, d) for d in range(1, 32)], [60.0] * 30 + [-1.0])

    results = {r.name: r.passed for r in check_currency_frame(df, min_rows=10)}

    assert results["курс больше нуля"] is False


def test_quality_detects_anomalous_jump():
    dates = [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(30)]
    df = make_currency_frame(dates, [60.0] * 29 + [600.0])

    results = {r.name: r.passed for r in check_currency_frame(df, min_rows=10)}

    assert results["нет аномальных скачков курса >3x"] is False


def test_key_rate_bounds():
    df = pd.DataFrame(
        {
            "rate_date": [dt.date(2020, 1, 1) + dt.timedelta(days=i) for i in range(60)],
            "key_rate_pct": [7.5] * 59 + [120.0],
        }
    )

    results = {r.name: r.passed for r in check_key_rate_frame(df, min_rows=10)}

    assert results["ставка в разумных пределах 0..100%"] is False


def test_enforce_raises_on_failed_check():
    df = make_currency_frame([dt.date(2020, 1, 1)], [60.0])

    with pytest.raises(QualityError):
        enforce(check_currency_frame(df, min_rows=10))  # строк меньше порога
