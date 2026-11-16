"""Загрузка и валидация конфигурации."""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_PATH = Path(os.environ.get("CBR_CONFIG", "config/config.yaml"))


@dataclass(frozen=True)
class ExtractConfig:
    currency_url: str
    key_rate_url: str
    currencies: dict[str, str]
    timeout_seconds: int = 30
    max_retries: int = 4
    chunk_years: int = 1


@dataclass(frozen=True)
class LoadConfig:
    engine: str = "duckdb"
    duckdb_path: str = "data/cbr.duckdb"
    # postgres://user:pass@host:5432/db
    db_url: str | None = None


@dataclass(frozen=True)
class TransformConfig:
    horizons_days: tuple[int, ...] = (30, 90, 180, 365, 1095)
    volatility_window_days: int = 30
    forecast_horizon_days: int = 30
    annualization_days: int = 252


@dataclass(frozen=True)
class Config:
    start_date: dt.date
    end_date: dt.date
    extract: ExtractConfig
    load: LoadConfig
    transform: TransformConfig
    report_dir: Path = field(default=Path("docs"))
    raw_dir: Path = field(default=Path("data/raw"))
    report_title: str = "Курс рубля и ключевая ставка"


def _as_date(value: str | dt.date | None, default: dt.date) -> dt.date:
    if value is None:
        return default
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def load_config(path: Path | str | None = None, today: dt.date | None = None) -> Config:
    """Читает yaml, подставляет «сегодня» и переменные окружения."""
    cfg_path = Path(path) if path else CONFIG_PATH
    with open(cfg_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    today = today or dt.date.today()
    pipeline = raw.get("pipeline") or {}
    load_raw = raw.get("load") or {}
    transform_raw = raw.get("transform") or {}
    report_raw = raw.get("report") or {}

    start = _as_date(pipeline.get("start_date"), today.replace(month=1, day=1))
    end = _as_date(pipeline.get("end_date"), today)
    if start >= end:
        raise ValueError(f"start_date ({start}) должен быть раньше end_date ({end})")

    return Config(
        start_date=start,
        end_date=end,
        extract=ExtractConfig(**raw["extract"]),
        load=LoadConfig(
            engine=os.environ.get("CBR_ENGINE", load_raw.get("engine", "duckdb")),
            duckdb_path=os.environ.get(
                "CBR_DUCKDB_PATH", load_raw.get("duckdb_path", "data/cbr.duckdb")
            ),
            db_url=os.environ.get("DB_URL"),
        ),
        transform=TransformConfig(
            horizons_days=tuple(transform_raw.get("horizons_days", (30, 90, 180, 365))),
            volatility_window_days=int(transform_raw.get("volatility_window_days", 30)),
            forecast_horizon_days=int(transform_raw.get("forecast_horizon_days", 30)),
            annualization_days=int(transform_raw.get("annualization_days", 252)),
        ),
        report_dir=Path(report_raw.get("output_dir", "docs")),
        report_title=report_raw.get("title", "Курс рубля и ключевая ставка"),
    )
