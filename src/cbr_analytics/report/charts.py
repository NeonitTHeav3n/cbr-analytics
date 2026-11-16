"""Минимальный набор SVG-графиков без внешних зависимостей.

Зачем свой SVG, а не plotly/altair: дашборд должен быть одним файлом,
который открывается офлайн и не тянет CDN — его можно приложить к резюме
и он не сломается через год.
"""

from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass

PALETTE = ["#2f6feb", "#e8613c", "#0f9d58", "#8b5cf6", "#e0a80d"]


@dataclass
class Series:
    name: str
    points: list[tuple[dt.date, float]]
    color: str = PALETTE[0]
    kind: str = "line"  # line | area
    dashed: bool = False

    def __post_init__(self) -> None:
        self.points = sorted((d, v) for d, v in self.points if v is not None)


@dataclass
class Axis:
    """Общий каркас графика: сетка, оси, подписи."""

    width: int = 860
    height: int = 300
    pad_left: int = 62
    pad_right: int = 18
    pad_top: int = 16
    pad_bottom: int = 34
    y_ticks: int = 5
    x_labels: int = 6


def _nice_ticks(lo: float, hi: float, count: int) -> list[float]:
    if hi == lo:
        hi = lo + 1
    raw_step = (hi - lo) / max(count - 1, 1)
    magnitude = 10 ** len(str(int(abs(raw_step)))) / 10 if raw_step else 1
    magnitude = max(magnitude, 1e-9)
    for mult in (0.5, 1, 2, 2.5, 5, 10):
        step = magnitude * mult
        if step >= raw_step:
            break
    start = (lo // step) * step
    ticks, value = [], start
    while value < hi + step:
        ticks.append(round(value, 10))
        value += step
    return ticks


def _fmt(value: float, digits: int = 2) -> str:
    text = f"{value:,.{digits}f}".replace(",", " ")
    return text.replace(".", ",")


def _log_ticks(values: list[float], count: int = 5) -> list[float]:
    """Подписи для лог-шкалы: 1-2-5 внутри каждого порядка (10, 20, 50, 100, ...)."""
    lo, hi = min(values) * 0.85, max(values) * 1.15  # запас, чтобы шкала не обрезала линию
    ticks: list[float] = []
    for decade in range(-3, 7):
        for mult in (1, 2, 5):
            value = mult * 10**decade
            if lo <= value <= hi:
                ticks.append(float(value))
    if len(ticks) < 2:  # страховка для очень узкого диапазона
        return _nice_ticks(lo, hi, count)
    if len(ticks) > count + 3:
        step = len(ticks) / (count + 1)
        ticks = [ticks[int(round(i * step))] for i in range(count + 1)]
    return ticks


def line_chart(
    series: list[Series],
    *,
    axis: Axis | None = None,
    y_digits: int = 2,
    y_suffix: str = "",
    x_as_percent: bool = False,
    zero_line: bool = False,
    log_scale: bool = False,
) -> str:
    """Линейный график. log_scale полезен, когда в одном поле величины разного порядка
    (юань ≈ 12 ₽ и евро ≈ 91 ₽): на лог-шкале сравнимы относительные изменения."""
    axis = axis or Axis()
    all_points = [p for s in series for p in s.points]
    if not all_points:
        return "<p class='muted'>нет данных</p>"

    dates = [d for d, _ in all_points]
    values = [v for _, v in all_points]
    x_min, x_max = min(dates).toordinal(), max(dates).toordinal()

    if log_scale:
        import math

        transform = math.log10
        y_min, y_max = transform(min(values)), transform(max(values))
        y_ticks = [transform(v) for v in _log_ticks(values)]
        y_labels = {
            transform(v): _fmt(v, 0 if v >= 10 else 2) + y_suffix for v in _log_ticks(values)
        }
    else:
        transform = float
        y_min, y_max = min(values), max(values)
        if zero_line:
            y_min, y_max = min(y_min, 0), max(y_max, 0)
        y_ticks = _nice_ticks(y_min, y_max, axis.y_ticks)
        y_labels = {}
    y_lo, y_hi = min(y_ticks + [y_min]), max(y_ticks + [y_max])

    plot_w = axis.width - axis.pad_left - axis.pad_right
    plot_h = axis.height - axis.pad_top - axis.pad_bottom

    def sx(d: dt.date) -> float:
        span = max(x_max - x_min, 1)
        return axis.pad_left + (d.toordinal() - x_min) / span * plot_w

    def sy(v: float) -> float:
        span = max(y_hi - y_lo, 1e-9)
        return axis.pad_top + plot_h - (v - y_lo) / span * plot_h

    parts: list[str] = [f'<svg viewBox="0 0 {axis.width} {axis.height}" class="chart" role="img">']
    # сетка + подписи Y
    for tick in y_ticks:
        y = sy(tick)
        parts.append(
            f'<line x1="{axis.pad_left}" y1="{y:.1f}" '
            f'x2="{axis.width - axis.pad_right}" y2="{y:.1f}" '
            f'stroke="#e6e9ef" stroke-width="1"/>'
        )
        if log_scale:
            label = y_labels.get(tick, "")
        elif x_as_percent:
            label = _fmt(tick * 100, 0) + "%"
        else:
            label = _fmt(tick, y_digits) + y_suffix
        parts.append(
            f'<text x="{axis.pad_left - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="#8a93a3">{label}</text>'
        )
    # подписи X
    step = max((x_max - x_min) // max(axis.x_labels - 1, 1), 1)
    tick_ord = x_min
    while tick_ord <= x_max:
        d = dt.date.fromordinal(tick_ord)
        parts.append(
            f'<text x="{sx(d):.1f}" y="{axis.height - 10}" text-anchor="middle" '
            f'font-size="11" fill="#8a93a3">{d:%m.%Y}</text>'
        )
        tick_ord += step

    # серии
    for s in series:
        if len(s.points) < 2:
            continue
        coords = [(sx(d), sy(transform(v))) for d, v in s.points]
        path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in coords)
        if s.kind == "area":
            base = sy(y_lo if log_scale else max(y_lo, 0))
            area = path + f" L {coords[-1][0]:.1f} {base:.1f} L {coords[0][0]:.1f} {base:.1f} Z"
            parts.append(f'<path d="{area}" fill="{s.color}" fill-opacity="0.12" stroke="none"/>')
        dash = ' stroke-dasharray="4 3"' if s.dashed else ""
        parts.append(
            f'<path d="{path}" fill="none" stroke="{s.color}" stroke-width="2"{dash} '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
    parts.append("</svg>")

    legend = "".join(
        f'<span class="lg"><i style="background:{s.color}"></i>{html.escape(s.name)}</span>'
        for s in series
    )
    return f'<div class="legend">{legend}</div>' + "".join(parts)


def grouped_bars(
    categories: list[str],
    groups: list[tuple[str, list[float], str]],
    *,
    width: int = 860,
    height: int = 260,
    y_suffix: str = "%",
    max_value: float | None = None,
    value_digits: int = 0,
) -> str:
    pad_left, pad_right, pad_top, pad_bottom = 62, 18, 16, 46
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    top = max_value if max_value is not None else max(max(v) for _, v, _ in groups)

    def sy(v: float) -> float:
        return pad_top + plot_h - (v / top) * plot_h

    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart" role="img">']
    for i in range(5):
        v = top * i / 4
        y = sy(v)
        parts.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{width - pad_right}" y2="{y:.1f}" '
            f'stroke="#e6e9ef"/>'
        )
        parts.append(
            f'<text x="{pad_left - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" '
            f'fill="#8a93a3">{_fmt(v, value_digits)}{y_suffix}</text>'
        )

    slot = plot_w / len(categories)
    bar_w = slot * 0.8 / len(groups)
    for ci, cat in enumerate(categories):
        base_x = pad_left + slot * ci + slot * 0.1
        for gi, (_, values, color) in enumerate(groups):
            v = values[ci]
            x = base_x + bar_w * gi
            y = sy(v)
            h = max(sy(0) - y, 0)
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w - 3:.1f}" height="{h:.1f}" '
                f'fill="{color}" rx="2">'
                f"<title>{html.escape(cat)}: {_fmt(v, value_digits)}{y_suffix}</title></rect>"
            )
        parts.append(
            f'<text x="{pad_left + slot * ci + slot / 2:.1f}" y="{height - 14}" '
            f'text-anchor="middle" font-size="11" fill="#5b6472">{html.escape(cat)}</text>'
        )
    parts.append("</svg>")
    legend = "".join(
        f'<span class="lg"><i style="background:{color}"></i>{html.escape(name)}</span>'
        for name, _, color in groups
    )
    return f'<div class="legend">{legend}</div>' + "".join(parts)
