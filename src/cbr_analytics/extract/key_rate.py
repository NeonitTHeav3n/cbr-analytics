"""Extract: ключевая ставка ЦБ РФ.

Источник: SOAP-сервис https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx,
операция KeyRateXML(fromDate, ToDate) — официальные данные, без токена.
Особенность API: имена параметров несимметричны (fromDate / ToDate),
это видно в WSDL, и на этом легко спотыкается: при ошибке сервис
возвращает 200 с пустым <KeyRate><Error /></KeyRate>.
"""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd

from cbr_analytics.config import ExtractConfig
from cbr_analytics.extract.currency import _chunk_bounds
from cbr_analytics.http import fetch_with_retry, get_logger

log = get_logger(__name__)

COLUMNS = ["rate_date", "key_rate_pct"]
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"


def build_soap_request(start: dt.date, end: dt.date) -> bytes:
    envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="{SOAP_NS}">
  <soap:Body>
    <KeyRateXML xmlns="http://web.cbr.ru/">
      <fromDate>{start.isoformat()}T00:00:00</fromDate>
      <ToDate>{end.isoformat()}T00:00:00</ToDate>
    </KeyRateXML>
  </soap:Body>
</soap:Envelope>"""
    return envelope.encode("utf-8")


def parse_key_rate_xml(content: bytes) -> pd.DataFrame:
    """Достаёт пары <KR><DT/><Rate/></KR> из SOAP-ответа."""
    root = ET.fromstring(content)
    rows: list[tuple[dt.date, float]] = []
    for kr in root.iter():
        if not kr.tag.endswith("KR"):
            continue
        dt_text = kr.findtext("DT")
        rate_text = kr.findtext("Rate")
        if not (dt_text and rate_text):
            continue
        rows.append((dt.date.fromisoformat(dt_text[:10]), float(rate_text.replace(",", "."))))
    df = pd.DataFrame(rows, columns=COLUMNS)
    if df.empty:
        raise ValueError("CBR вернул пустой ответ по ключевой ставке (проверь имена полей SOAP)")
    return df


def _raw_path(raw_dir: Path, start: dt.date, end: dt.date) -> Path:
    return raw_dir / "key_rate" / f"{start:%Y-%m-%d}_{end:%Y-%m-%d}.xml"


def extract_key_rate(
    cfg: ExtractConfig, start: dt.date, end: dt.date, raw_dir: Path, *, force: bool = False
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for chunk_start, chunk_end in _chunk_bounds(start, end, cfg.chunk_years):
        path = _raw_path(raw_dir, chunk_start, chunk_end)
        if path.exists() and not force:
            content = path.read_bytes()
            log.info("из кэша: %s", path.name)
        else:
            log.info("запрос CBR (ключевая ставка): %s..%s", chunk_start, chunk_end)
            content = fetch_with_retry(
                cfg.key_rate_url,
                method="POST",
                content=build_soap_request(chunk_start, chunk_end),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": '"http://web.cbr.ru/KeyRateXML"',
                },
                timeout=cfg.timeout_seconds,
                max_retries=cfg.max_retries,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        frames.append(parse_key_rate_xml(content))

    df = pd.concat(frames, ignore_index=True)
    df = df.drop_duplicates(subset=["rate_date"], keep="last")
    return df.sort_values("rate_date").reset_index(drop=True)
