"""Общие утилиты: логирование и HTTP с ретраями."""

from __future__ import annotations

import logging
import sys
import time

import httpx

LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(level=level, format=LOG_FORMAT, datefmt="%H:%M:%S", stream=sys.stderr)
    # httpx на INFO слишком болтлив
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def fetch_with_retry(
    url: str,
    *,
    params: dict | None = None,
    method: str = "GET",
    content: bytes | None = None,
    headers: dict | None = None,
    timeout: int = 30,
    max_retries: int = 4,
    logger: logging.Logger | None = None,
) -> bytes:
    """HTTP-запрос с экспоненциальным backoff.

    Возвращает сырые байты: cbr.ru отдаёт windows-1251, а разбирать XML
    нужно вместе с объявленной кодировкой — поэтому декодированием
    занимается парсер, а не этот слой.
    """
    log = logger or get_logger("http")
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        try:
            response = httpx.request(
                method, url, params=params, content=content, headers=headers, timeout=timeout
            )
            response.raise_for_status()
            if not response.content:
                raise ValueError(f"пустой ответ от {url}")
            return response.content
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            # 4xx кроме 429 бессмысленно ретраить
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                if exc.response.status_code != 429:
                    raise
            if attempt == max_retries:
                break
            sleep_for = min(2**attempt, 30)
            log.warning(
                "запрос не удался (%s), попытка %s/%s, пауза %ss",
                exc,
                attempt,
                max_retries,
                sleep_for,
            )
            time.sleep(sleep_for)

    raise RuntimeError(f"не удалось выполнить запрос {url}") from last_error
