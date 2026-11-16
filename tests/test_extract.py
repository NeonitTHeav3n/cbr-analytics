"""Тесты парсеров. Сети нет: работаем на сохранённых ответах ЦБ (tests/fixtures)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from cbr_analytics.extract.currency import _chunk_bounds, parse_currency_xml
from cbr_analytics.extract.key_rate import build_soap_request, parse_key_rate_xml

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_currency_xml_basic():
    df = parse_currency_xml((FIXTURES / "currency_usd_2024.xml").read_bytes(), "USD")

    assert list(df.columns) == ["rate_date", "char_code", "nominal", "rate_per_unit"]
    assert len(df) == 3
    assert df.iloc[0]["rate_date"] == dt.date(2024, 1, 3)
    # десятичная запятая из windows-1251 XML разобрана в float
    assert df.iloc[0]["rate_per_unit"] == pytest.approx(90.404)
    assert df.iloc[-1]["rate_per_unit"] == pytest.approx(88.7818)


def test_parse_currency_normalizes_nominal():
    """У JPY номинал 100 — курс должен считаться за одну единицу, а не за 100."""
    df = parse_currency_xml((FIXTURES / "currency_jpy_nominal100.xml").read_bytes(), "JPY")

    assert df.iloc[0]["nominal"] == 100
    assert df.iloc[0]["rate_per_unit"] == pytest.approx(0.615)


def test_parse_key_rate_xml():
    df = parse_key_rate_xml((FIXTURES / "key_rate_2024.xml").read_bytes())

    assert list(df.columns) == ["rate_date", "key_rate_pct"]
    assert len(df) == 4
    assert df["key_rate_pct"].eq(16.0).all()
    assert df["rate_date"].max() == dt.date(2024, 1, 10)


def test_parse_key_rate_raises_on_error_response():
    """Пустой ответ (неверные имена полей SOAP) должен падать громко, а не молча."""
    with pytest.raises(ValueError, match="пустой ответ"):
        parse_key_rate_xml((FIXTURES / "key_rate_empty.xml").read_bytes())


def test_soap_request_uses_exact_field_names():
    """В WSDL поля называются fromDate / ToDate — именно большая T ломает запрос."""
    body = build_soap_request(dt.date(2024, 1, 1), dt.date(2024, 2, 1)).decode()

    assert "<fromDate>2024-01-01T00:00:00</fromDate>" in body
    assert "<ToDate>2024-02-01T00:00:00</ToDate>" in body
    assert "KeyRateXML" in body


@pytest.mark.parametrize(
    ("years", "expected_chunks"),
    [(1, 3), (2, 2), (3, 1)],
)
def test_chunk_bounds_cover_range_without_overlap(years, expected_chunks):
    start, end = dt.date(2020, 1, 1), dt.date(2022, 6, 15)
    bounds = _chunk_bounds(start, end, years)

    assert len(bounds) == expected_chunks
    assert bounds[0][0] == start
    assert bounds[-1][1] == end
    for (_, prev_end), (next_start, _) in zip(bounds, bounds[1:], strict=False):
        assert next_start == prev_end + dt.timedelta(days=1)


def test_chunk_bounds_handles_leap_day():
    bounds = _chunk_bounds(dt.date(2024, 2, 29), dt.date(2025, 3, 1), 1)
    assert bounds[0] == (dt.date(2024, 2, 29), dt.date(2025, 2, 27))
