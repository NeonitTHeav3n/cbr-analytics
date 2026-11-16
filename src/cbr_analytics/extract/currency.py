"""Extract: официальные курсы валют ЦБ РФ.

Источник: https://www.cbr.ru/scripts/XML_dynamic.asp — XML в windows-1251,
история с 1999 года, без токена и регистрации.

Принципы:
* сырой ответ сохраняем как есть (data/raw/...) — это наш bronze-слой;
* уже скачанный кусок повторно не качаем (если не передан force);
* один запрос = один год, чтобы сбой не стоил всей истории.
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

from cbr_analytics.config import ExtractConfig
from cbr_analytics.http import fetch_with_retry, get_logger

log = get_logger(__name__)

COLUMNS = ["rate_date", "char_code", "nominal", "rate_per_unit"]


def parse_currency_xml(content: bytes, char_code: str) -> pd.DataFrame:
    """Разбирает ответ XML_dynamic.asp в таблицу.

    Nominal у части валют не 1 (например, у JPY — 100), поэтому всегда
    считаем курс за одну единицу: value / nominal.
    """
    root = ET.fromstring(content)  # объявление encoding="windows-1251" внутри файла
    rows: list[tuple] = []
    for record in root.findall("Record"):
        date_raw = record.attrib.get("Date")
        nominal_raw = record.findtext("Nominal")
        value_raw = record.findtext("Value")
        if not (date_raw and nominal_raw and value_raw):
            continue
        nominal = int(float(nominal_raw.replace(",", ".")))
        value = float(value_raw.replace(",", "."))
        rows.append(
            (dt.datetime.strptime(date_raw, "%d.%m.%Y").date(), char_code, nominal, value / nominal)
        )
    return pd.DataFrame(rows, columns=COLUMNS)


def _chunk_bounds(start: dt.date, end: dt.date, years: int) -> list[tuple[dt.date, dt.date]]:
    bounds = []
    cursor = start
    while cursor <= end:
        try:
            nxt = cursor.replace(year=cursor.year + years) - dt.timedelta(days=1)
        except ValueError:  # 29 февраля
            nxt = cursor.replace(year=cursor.year + years, day=28) - dt.timedelta(days=1)
        bounds.append((cursor, min(nxt, end)))
        cursor = min(nxt, end) + dt.timedelta(days=1)
    return bounds


def _raw_path(raw_dir: Path, char_code: str, start: dt.date, end: dt.date) -> Path:
    # партиционирование по валюте и году: идемпотентно и легко перезапускается
    return raw_dir / "currency" / f"char_code={char_code}" / f"{start:%Y-%m-%d}_{end:%Y-%m-%d}.xml"


def extract_currency(
    cfg: ExtractConfig, start: dt.date, end: dt.date, raw_dir: Path, *, force: bool = False
) -> pd.DataFrame:
    """Скачивает историю по каждой валюте из конфига и возвращает общий DataFrame."""
    frames: list[pd.DataFrame] = []
    for char_code, val_id in cfg.currencies.items():
        for chunk_start, chunk_end in _chunk_bounds(start, end, cfg.chunk_years):
            path = _raw_path(raw_dir, char_code, chunk_start, chunk_end)
            if path.exists() and not force:
                content = path.read_bytes()
                log.info("из кэша: %s", path.relative_to(raw_dir.parent.parent))
            else:
                log.info("запрос CBR: %s %s..%s", char_code, chunk_start, chunk_end)
                content = fetch_with_retry(
                    cfg.currency_url,
                    params={
                        "date_req1": chunk_start.strftime("%d/%m/%Y"),
                        "date_req2": chunk_end.strftime("%d/%m/%Y"),
                        "VAL_NM_RQ": val_id,
                    },
                    timeout=cfg.timeout_seconds,
                    max_retries=cfg.max_retries,
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            frames.append(parse_currency_xml(content, char_code))

    if not frames:
        raise RuntimeError("не удалось получить ни одного куска истории курсов")

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["rate_date", "char_code"], keep="last")
    return df.sort_values(["char_code", "rate_date"]).reset_index(drop=True)
