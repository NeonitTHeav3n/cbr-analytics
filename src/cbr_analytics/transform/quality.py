"""Проверки качества данных: до загрузки (на DataFrame) и после (на витринах)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from cbr_analytics.http import get_logger

log = get_logger(__name__)


class QualityError(RuntimeError):
    """Данные не прошли проверку — пайплайн останавливается, а не пишет мусор в витрины."""


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


def check_currency_frame(df: pd.DataFrame, *, min_rows: int = 100) -> list[CheckResult]:
    results: list[CheckResult] = []

    results.append(
        CheckResult(
            "есть данные", len(df) >= min_rows, f"строк: {len(df)} (ожидалось >= {min_rows})"
        )
    )
    results.append(
        CheckResult(
            "нет пропусков в ключевых полях",
            not df[["rate_date", "char_code", "rate_per_unit"]].isna().any().any(),
        )
    )
    results.append(
        CheckResult(
            "курс больше нуля",
            bool((df["rate_per_unit"] > 0).all()),
            f"min={df['rate_per_unit'].min():.4f}",
        )
    )
    dups = df.duplicated(subset=["rate_date", "char_code"]).sum()
    results.append(CheckResult("нет дублей (дата, валюта)", bool(dups == 0), f"дублей: {dups}"))

    # Курс не может меняться в 3 раза за день даже в 2022-м — ловим битые записи
    wide = df.pivot_table(index="rate_date", columns="char_code", values="rate_per_unit")
    jumps = (wide / wide.shift(1)).apply(lambda s: (s > 3).sum() + (s < 1 / 3).sum()).sum()
    results.append(
        CheckResult("нет аномальных скачков курса >3x", bool(jumps == 0), f"скачков: {int(jumps)}")
    )
    return results


def check_key_rate_frame(df: pd.DataFrame, *, min_rows: int = 50) -> list[CheckResult]:
    results: list[CheckResult] = []
    results.append(CheckResult("есть данные", len(df) >= min_rows, f"строк: {len(df)}"))
    results.append(
        CheckResult(
            "ставка в разумных пределах 0..100%",
            bool(df["key_rate_pct"].between(0, 100).all()),
            f"min={df['key_rate_pct'].min()}, max={df['key_rate_pct'].max()}",
        )
    )
    dups = df.duplicated(subset=["rate_date"]).sum()
    results.append(CheckResult("нет дублей по дате", bool(dups == 0), f"дублей: {dups}"))
    return results


# Проверки на уровне витрин: (имя, sql, ожидание)
MART_CHECKS: list[tuple[str, str, str]] = [
    (
        "в mart_deposit_vs_fx нет пропущенных доходностей",
        "SELECT COUNT(*) FROM mart_deposit_vs_fx WHERE deposit_return IS NULL OR fx_return IS NULL",
        "== 0",
    ),
    (
        "доходность депозита неотрицательна",
        "SELECT COUNT(*) FROM mart_deposit_vs_fx WHERE deposit_return < 0",
        "== 0",
    ),
    (
        "горизонты посчитаны по каждому дню",
        "SELECT COUNT(DISTINCT horizon_days) FROM mart_deposit_vs_fx",
        ">= 3",
    ),
    (
        "доля побед вклада в [0,1]",
        "SELECT COUNT(*) FROM mart_headline WHERE deposit_win_share < 0 OR deposit_win_share > 1",
        "== 0",
    ),
    (
        "в mart_fx_monthly нет нулевых курсов",
        "SELECT COUNT(*) FROM mart_fx_monthly WHERE rate_end_of_month <= 0",
        "== 0",
    ),
    (
        "коридор прогноза упорядочен",
        "SELECT COUNT(*) FROM mart_forecast_band WHERE band_low_95 >= band_high_95",
        "== 0",
    ),
]


def _evaluate(value: float, expectation: str) -> bool:
    op, _, expected = expectation.partition(" ")
    expected_value = float(expected)
    return {
        "==": value == expected_value,
        ">=": value >= expected_value,
        ">": value > expected_value,
        "<=": value <= expected_value,
        "<": value < expected_value,
    }[op]


def run_mart_checks(query, checks: list[tuple[str, str, str]] | None = None) -> list[CheckResult]:
    """query(sql) -> DataFrame. Ожидания описаны строкой, чтобы их было видно в отчёте."""
    results: list[CheckResult] = []
    for name, sql, expectation in checks or MART_CHECKS:
        value = float(query(sql).iloc[0, 0])
        results.append(
            CheckResult(
                name, _evaluate(value, expectation), f"получено {value:g}, нужно {expectation}"
            )
        )
    return results


def enforce(results: list[CheckResult]) -> None:
    """Печатает отчёт и падает, если хоть одна проверка не прошла."""
    failed = [r for r in results if not r.passed]
    for r in results:
        log.log(
            20 if r.passed else 40,
            "%s %s%s",
            "OK  " if r.passed else "FAIL",
            r.name,
            f" ({r.detail})" if r.detail else "",
        )
    if failed:
        raise QualityError(f"не пройдено проверок: {len(failed)} из {len(results)}")
