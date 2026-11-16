"""Transform: приведение сырых данных к аккуратным таблицам.

Вся бизнес-логика (протяжка на выходные, депозитный индекс, метрики) живёт в SQL —
здесь только типы, сортировка и отсечение мусора, чтобы SQL был читаемым.
"""

from __future__ import annotations

import pandas as pd

from cbr_analytics.http import get_logger

log = get_logger(__name__)

CURRENCY_DTYPES = {
    "rate_date": "object",
    "char_code": "object",
    "nominal": "int64",
    "rate_per_unit": "float64",
}


def clean_currency(df: pd.DataFrame, start, end) -> pd.DataFrame:
    out = df.copy()
    out["rate_date"] = pd.to_datetime(out["rate_date"]).dt.date
    out["char_code"] = out["char_code"].astype(str).str.strip().str.upper()
    out["nominal"] = out["nominal"].astype("int64")
    out["rate_per_unit"] = out["rate_per_unit"].astype("float64")

    # CBR иногда отдаёт граничные даты за пределами запрошенного окна — отсекаем
    out = out[(out["rate_date"] >= start) & (out["rate_date"] <= end)]
    out = out[out["rate_per_unit"] > 0]
    out = out.drop_duplicates(subset=["rate_date", "char_code"], keep="last")
    out = out.sort_values(["char_code", "rate_date"]).reset_index(drop=True)
    log.info("курсы: %s строк, %s..%s", len(out), out["rate_date"].min(), out["rate_date"].max())
    return out


def clean_key_rate(df: pd.DataFrame, start, end) -> pd.DataFrame:
    out = df.copy()
    out["rate_date"] = pd.to_datetime(out["rate_date"]).dt.date
    out["key_rate_pct"] = out["key_rate_pct"].astype("float64")
    out = out[(out["rate_date"] >= start) & (out["rate_date"] <= end)]
    out = out.drop_duplicates(subset=["rate_date"], keep="last")
    out = out.sort_values("rate_date").reset_index(drop=True)
    log.info(
        "ключевая ставка: %s строк, %s..%s",
        len(out),
        out["rate_date"].min(),
        out["rate_date"].max(),
    )
    return out
