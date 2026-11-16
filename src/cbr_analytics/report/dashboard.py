"""Сборка дашборда: витрины -> один самодостаточный HTML + PNG для README."""

from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

import pandas as pd

from cbr_analytics.config import Config
from cbr_analytics.http import get_logger
from cbr_analytics.report.charts import PALETTE, Axis, Series, grouped_bars, line_chart

log = get_logger(__name__)

CURRENCY_NAMES = {"USD": "Доллар США", "EUR": "Евро", "CNY": "Юань"}
COLOR_BY_CODE = {"USD": PALETTE[0], "EUR": PALETTE[1], "CNY": PALETTE[2]}


# ---------- форматирование ----------
def num(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:+,.{digits}f}".replace(",", " ").replace(".", ",") + "%"


def pct_abs(value: float, digits: int = 1) -> str:
    return f"{value * 100:,.{digits}f}".replace(",", " ").replace(".", ",") + "%"


def horizon_label(days: int) -> str:
    if days % 365 == 0 and days >= 365:
        years = days // 365
        return "1 год" if years == 1 else f"{years} года" if years < 5 else f"{years} лет"
    if days % 30 == 0 and days >= 30:
        return f"{days // 30} мес"
    return f"{days} дн"


# ---------- данные ----------
def collect(warehouse, cfg: Config) -> dict[str, pd.DataFrame]:
    q = warehouse.query
    return {
        "monthly": q("SELECT * FROM mart_fx_monthly ORDER BY month"),
        "vol": q("SELECT * FROM mart_volatility ORDER BY rate_date"),
        "headline": q("SELECT * FROM mart_headline ORDER BY horizon_days, char_code"),
        "index": q("SELECT * FROM mart_monthly_index ORDER BY month"),
        "band": q("SELECT * FROM mart_forecast_band ORDER BY char_code"),
    }


def latest_spot(monthly: pd.DataFrame) -> dict[str, tuple[float, float]]:
    """Курс на последнюю дату и изменение за месяц."""
    last = monthly.sort_values("month").groupby("char_code").tail(1)
    return {
        row.char_code: (float(row.rate_end_of_month), float(row.mom_change or 0.0))
        for row in last.itertuples()
    }


def findings(data: dict[str, pd.DataFrame]) -> list[str]:
    """Текстовые выводы, посчитанные из данных — не вписаны руками."""
    head = data["headline"]
    vol = data["vol"]
    out: list[str] = []

    usd_1y = head[(head.char_code == "USD") & (head.horizon_days == 365)].iloc[0]
    out.append(
        f"На горизонте года рублёвый вклад под ключевую ставку обгонял доллар в "
        f"<b>{pct_abs(usd_1y.deposit_win_share, 0)}</b> случаев (медианный перевес "
        f"{num(usd_1y.diff_pp_median * 100, 1)} п.п.)."
    )

    longest = head.sort_values("horizon_days").horizon_days.max()
    long_row = head[(head.char_code == "USD") & (head.horizon_days == longest)].iloc[0]
    out.append(
        f"Чем длиннее горизонт, тем чаще выигрывает вклад: на {horizon_label(int(longest))} "
        f"доля побед — <b>{pct_abs(long_row.deposit_win_share, 0)}</b>, но разброс исходов "
        f"тоже растёт (от {num(long_row.diff_pp_p10 * 100, 0)} до {num(long_row.diff_pp_p90 * 100, 0)} п.п.)."
    )

    short = head[head.horizon_days == head.horizon_days.min()]
    out.append(
        f"На коротком горизонте ({horizon_label(int(head.horizon_days.min()))}) преимущество почти "
        f"исчезает: доля побед {pct_abs(short.deposit_win_share.min(), 0)}–"
        f"{pct_abs(short.deposit_win_share.max(), 0)}, то есть это лотерея, а не стратегия."
    )

    peak = vol.loc[vol.vol_annualized.idxmax()]
    out.append(
        f"Максимум волатильности — <b>{pct_abs(peak.vol_annualized, 0)}</b> годовых "
        f"({pd.to_datetime(peak.rate_date):%m.%Y}, {peak.char_code})."
    )
    return out


# ---------- разметка ----------
def kpi_card(label: str, value: str, delta: str | None = None, hint: str = "") -> str:
    delta_html = ""
    if delta:
        cls = "up" if not delta.startswith(("-", "−")) else "down"
        delta_html = f'<span class="delta {cls}">{html.escape(delta)}</span>'
    return (
        f'<div class="kpi"><div class="kpi-label">{html.escape(label)}</div>'
        f'<div class="kpi-value">{value}{delta_html}</div>'
        f'<div class="kpi-hint">{hint}</div></div>'
    )


def table(df: pd.DataFrame, headers: dict[str, str], formatters: dict[str, callable]) -> str:  # type: ignore[valid-type]
    thead = "".join(f"<th>{html.escape(h)}</th>" for h in headers.values())
    rows = []
    for row in df.itertuples(index=False):
        cells = []
        for col in headers:
            value = getattr(row, col)
            fmt = formatters.get(col)
            cells.append(f"<td>{fmt(value) if fmt else value}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


STYLE = """
:root { --ink:#111827; --muted:#6b7280; --line:#e5e7eb; --bg:#ffffff; --soft:#f7f8fa;
        --blue:#2f6feb; --green:#0f9d58; --red:#e8613c; }
* { box-sizing: border-box; }
body { margin:0; background:var(--soft); color:var(--ink);
       font:15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
.wrap { max-width: 940px; margin: 0 auto; padding: 32px 20px 64px; }
header h1 { font-size: 28px; margin: 0 0 6px; letter-spacing: -0.4px; }
header p { color: var(--muted); margin: 0; }
.badges { margin-top: 12px; display:flex; gap:8px; flex-wrap:wrap; }
.badge { background:#eef2ff; color:#3730a3; border-radius:999px; padding:3px 10px; font-size:12px; }
.card { background:var(--bg); border:1px solid var(--line); border-radius:14px; padding:20px 22px;
        margin-top:18px; box-shadow:0 1px 2px rgba(16,24,40,.04); }
.card h2 { font-size:17px; margin:0 0 4px; }
.card .sub { color:var(--muted); font-size:13px; margin:0 0 14px; }
.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-top:18px; }
.kpi { background:var(--bg); border:1px solid var(--line); border-radius:14px; padding:14px 16px; }
.kpi-label { font-size:12px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
.kpi-value { font-size:22px; font-weight:650; margin-top:4px; }
.kpi-hint { font-size:12px; color:var(--muted); margin-top:2px; }
.delta { font-size:13px; font-weight:600; margin-left:8px; }
.delta.up { color:var(--green); } .delta.down { color:var(--red); }
.chart { width:100%; height:auto; display:block; }
.legend { display:flex; gap:16px; flex-wrap:wrap; font-size:12px; color:var(--muted); margin-bottom:6px; }
.lg i { display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:6px; }
table { width:100%; border-collapse:collapse; font-size:13.5px; margin-top:8px; }
th { text-align:right; font-weight:600; color:var(--muted); font-size:12px; text-transform:uppercase;
     letter-spacing:.03em; border-bottom:1px solid var(--line); padding:8px 6px; }
th:first-child, td:first-child { text-align:left; }
td { text-align:right; padding:8px 6px; border-bottom:1px solid #f1f3f7; font-variant-numeric:tabular-nums; }
tbody tr:hover { background:#fafbfd; }
ul.findings { margin:6px 0 0; padding-left:20px; }
ul.findings li { margin-bottom:8px; }
.foot { color:var(--muted); font-size:12.5px; margin-top:22px; line-height:1.6; }
.muted { color:var(--muted); }
.note { background:#fff8e6; border:1px solid #f2e0b8; border-radius:10px; padding:10px 14px;
        font-size:13px; color:#6b5622; margin-top:12px; }
"""


def build_report(warehouse, cfg: Config) -> Path:
    data = collect(warehouse, cfg)
    monthly, head, index, band, vol = (
        data["monthly"],
        data["headline"],
        data["index"],
        data["band"],
        data["vol"],
    )
    spot = latest_spot(monthly)
    as_of = pd.to_datetime(vol.rate_date.max()).date()
    key_rate = float(monthly.sort_values("month").key_rate_avg.iloc[-1])
    ins = findings(data)

    # --- графики ---
    fx_series = [
        Series(
            name=f"{CURRENCY_NAMES.get(code, code)}, ₽",
            points=[
                (pd.to_datetime(r.month).date(), float(r.rate_end_of_month))
                for r in monthly[monthly.char_code == code].itertuples()
            ],
            color=COLOR_BY_CODE.get(code, PALETTE[3]),
        )
        for code in ["USD", "EUR", "CNY"]
    ]
    fx_chart = line_chart(
        fx_series, axis=Axis(height=300, pad_left=54), y_digits=1, y_suffix=" ₽", log_scale=True
    )

    rate_chart = line_chart(
        [
            Series(
                name="Ключевая ставка, % годовых",
                points=[
                    (pd.to_datetime(r.month).date(), float(r.key_rate_avg))
                    for r in monthly[monthly.char_code == "USD"].itertuples()
                ],
                color=PALETTE[3],
                kind="area",
            )
        ],
        axis=Axis(height=200, pad_left=54),
        y_digits=0,
        y_suffix="%",
    )

    usd_vol = vol[vol.char_code == "USD"]
    vol_chart = line_chart(
        [
            Series(
                name="Волатильность USD/RUB, 30 дней, % годовых",
                points=[
                    (pd.to_datetime(r.rate_date).date(), float(r.vol_annualized))
                    for r in usd_vol.itertuples()
                ],
                color=PALETTE[1],
                kind="area",
            )
        ],
        axis=Axis(height=210, pad_left=54),
        x_as_percent=True,
    )

    idx_base = index[index.char_code == "USD"]  # deposit_index_norm одинаков для всех строк месяца
    idx_series = [
        Series(
            name="Рублёвый вклад под ключевую ставку",
            points=[
                (pd.to_datetime(r.month).date(), float(r.deposit_index_norm))
                for r in idx_base.itertuples()
            ],
            color=PALETTE[3],
        )
    ] + [
        Series(
            name=f"{CURRENCY_NAMES.get(code, code)} в рублях",
            points=[
                (pd.to_datetime(r.month).date(), float(r.fx_index))
                for r in index[index.char_code == code].itertuples()
            ],
            color=COLOR_BY_CODE.get(code, PALETTE[0]),
        )
        for code in ["USD", "EUR"]
    ]
    index_chart = line_chart(
        idx_series, axis=Axis(height=280, pad_left=54), y_digits=2, y_suffix="×"
    )

    horizons = sorted(head.horizon_days.unique())
    codes = [c for c in ["USD", "EUR", "CNY"] if c in set(head.char_code)]
    win_chart = grouped_bars(
        [horizon_label(int(h)) for h in horizons],
        [
            (
                CURRENCY_NAMES.get(code, code),
                [
                    float(
                        head[
                            (head.horizon_days == h) & (head.char_code == code)
                        ].deposit_win_share.iloc[0]
                    )
                    * 100
                    for h in horizons
                ],
                COLOR_BY_CODE.get(code, PALETTE[0]),
            )
            for code in codes
        ],
        max_value=100,
        y_suffix="%",
    )

    head_table = head.copy()
    head_table["horizon"] = head_table.horizon_days.map(lambda d: horizon_label(int(d)))
    head_table["currency"] = head_table.char_code.map(lambda c: CURRENCY_NAMES.get(c, c))
    head_table = head_table[
        [
            "horizon",
            "currency",
            "n_observations",
            "deposit_win_share",
            "diff_pp_median",
            "diff_pp_p10",
            "diff_pp_p90",
        ]
    ]
    head_html = table(
        head_table,
        {
            "horizon": "Горизонт",
            "currency": "Валюта",
            "n_observations": "Наблюдений",
            "deposit_win_share": "Вклад выиграл",
            "diff_pp_median": "Медиана, п.п.",
            "diff_pp_p10": "p10",
            "diff_pp_p90": "p90",
        },
        {
            "n_observations": lambda v: f"{int(v):,}".replace(",", " "),
            "deposit_win_share": lambda v: pct_abs(v, 0),
            "diff_pp_median": lambda v: num(v * 100, 1),
            "diff_pp_p10": lambda v: num(v * 100, 1),
            "diff_pp_p90": lambda v: num(v * 100, 1),
        },
    )

    kpis = "".join(
        kpi_card(
            f"{code} / ₽",
            f"{num(spot[code][0], 2)} ₽",
            pct(spot[code][1], 1),
            CURRENCY_NAMES.get(code, code),
        )
        for code in spot
    )
    kpis += kpi_card("Ключевая ставка", f"{num(key_rate, 2)}%", None, "на конец периода")
    usd_365 = head[(head.char_code == "USD") & (head.horizon_days == 365)]
    if not usd_365.empty:
        kpis += kpi_card(
            "Вклад vs доллар, 1 год",
            pct_abs(float(usd_365.deposit_win_share.iloc[0]), 0),
            None,
            "доля случаев, где вклад выгоднее",
        )

    band_rows = "".join(
        f"<tr><td>{CURRENCY_NAMES.get(r.char_code, r.char_code)}</td>"
        f"<td>{num(r.spot, 2)} ₽</td><td>{pct_abs(r.vol_annualized, 1)}</td>"
        f"<td>{num(r.band_low_95, 2)} – {num(r.band_high_95, 2)} ₽</td></tr>"
        for r in band.itertuples()
    )

    findings_html = "".join(f"<li>{f}</li>" for f in ins)

    page = f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(cfg.report_title)}</title>
<style>{STYLE}</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>{html.escape(cfg.report_title)}</h1>
  <p>Данные Банка России на {as_of:%d.%m.%Y}. Курсы валют — официальные, ключевая ставка — официальная.</p>
  <div class="badges">
    <span class="badge">cbr.ru · XML_dynamic</span>
    <span class="badge">cbr.ru · KeyRateXML</span>
    <span class="badge">DuckDB</span>
    <span class="badge">{num(float(len(vol)), 0)} наблюдений</span>
  </div>
</header>

<div class="kpis">{kpis}</div>

<div class="card">
  <h2>Что показали данные</h2>
  <p class="sub">Каждый вывод посчитан в SQL и подставлен в текст автоматически.</p>
  <ul class="findings">{findings_html}</ul>
</div>

<div class="card">
  <h2>Курсы валют, ₽ за единицу</h2>
  <p class="sub">Конец месяца, логарифмическая шкала: юань и евро различаются в 7 раз, на обычной шкале
  линия юаня прижалась бы к нулю. Лог-шкала показывает относительные изменения.</p>
  {fx_chart}
</div>

<div class="card">
  <h2>Ключевая ставка</h2>
  <p class="sub">Средняя за месяц, % годовых. Это доходность «безрискового» рублёвого депозита в модели.</p>
  {rate_chart}
</div>

<div class="card">
  <h2>Волатильность доллара</h2>
  <p class="sub">Скользящее окно {cfg.transform.volatility_window_days} дней, аннуализированная σ по дневным лог-доходностям.</p>
  {vol_chart}
</div>

<div class="card">
  <h2>1 рубль: вклад против валюты</h2>
  <p class="sub">Накопленный результат с начала периода. Вклад — ежедневное начисление по ключевой ставке.</p>
  {index_chart}
</div>

<div class="card">
  <h2>Кто выигрывал: вклад или валюта</h2>
  <p class="sub">Доля дат старта, на которых рублёвый вклад дал больше, чем покупка валюты, % случаев.</p>
  {win_chart}
  {head_html}
</div>

<div class="card">
  <h2>Коридор на {cfg.transform.forecast_horizon_days} дней</h2>
  <p class="sub">Не прогноз: диапазон ±1,96σ из текущей исторической волатильности при допущении «ничего не меняется».</p>
  <table>
    <thead><tr><th>Валюта</th><th>Курс сейчас</th><th>Волатильность</th>
    <th>Коридор 95%</th></tr></thead>
    <tbody>{band_rows}</tbody>
  </table>
  <div class="note">Коридор отвечает на вопрос «какой разброс курса нормален», а не «какой курс будет».
  Модель случайного блуждания не знает про ставку, инфляцию, санкции и решения ЦБ.</div>
</div>

<div class="foot">
  <b>Методика.</b> Источник курсов — <code>cbr.ru/scripts/XML_dynamic.asp</code>, ключевой ставки —
  <code>DailyInfo.asmx · KeyRateXML</code>. Рублёвый вклад моделируется как ежедневное начисление
  <code>rate/100/365</code> без налога и без капитализации ограничений банка; валюта покупается и держится
  без комиссий. Доходности сравниваются в рублях. Все цифры пересчитываются из сырых XML-ответов
  одним прогоном <code>make all</code>.<br>
  <b>Ограничения.</b> Нет инфляции, налога на валютную переоценку и вклад, спреда банка и комиссий обменника.
  Доля побед вклада за 2015–2026 сильно зависит от периода: высокие ставки 2015 и 2022–2026 — это
  режим, а не закономерность рынка.
</div>
</div>
</body>
</html>
"""

    out_dir = cfg.report_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "dashboard.html"
    path.write_text(page, encoding="utf-8")
    log.info("дашборд готов: %s (%.0f КБ)", path, path.stat().st_size / 1024)

    _save_png(data, cfg, out_dir)
    (out_dir / "key_findings.md").write_text(_findings_md(ins, as_of), encoding="utf-8")
    return path


def _findings_md(items: list[str], as_of: dt.date) -> str:
    clean = [i.replace("<b>", "**").replace("</b>", "**") for i in items]
    lines = [f"# Ключевые выводы (данные на {as_of:%d.%m.%Y})", ""]
    lines += [f"{n}. {text}" for n, text in enumerate(clean, 1)]
    lines += [
        "",
        "> Файл генерируется автоматически из витрин: `make report`.",
    ]
    return "\n".join(lines)


def _save_png(data: dict[str, pd.DataFrame], cfg: Config, out_dir: Path) -> None:
    """Растр для README: превью дашборда нужно там, где HTML не открывают."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        log.warning("matplotlib не установлен — PNG пропускаю (pip install .[report])")
        return

    monthly = data["monthly"]
    vol = data["vol"][data["vol"].char_code == "USD"]
    index = data["index"][data["index"].char_code == "USD"]

    fig, axes = plt.subplots(2, 2, figsize=(13, 7.2), dpi=150)
    fig.suptitle(cfg.report_title, fontsize=14, fontweight="bold", x=0.06, ha="left")

    ax = axes[0][0]
    for code, color, name in [
        ("USD", "#2f6feb", "USD"),
        ("EUR", "#e8613c", "EUR"),
        ("CNY", "#0f9d58", "CNY"),
    ]:
        part = monthly[monthly.char_code == code]
        ax.plot(part.month, part.rate_end_of_month, color=color, label=name, lw=1.4)
    ax.set_title("Курс, ₽ за единицу", fontsize=10, loc="left")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[0][1]
    usd = monthly[monthly.char_code == "USD"]
    ax.plot(usd.month, usd.key_rate_avg, color="#8b5cf6", lw=1.6)
    ax.fill_between(usd.month, usd.key_rate_avg, color="#8b5cf6", alpha=0.15)
    ax.set_title("Ключевая ставка, % годовых", fontsize=10, loc="left")
    ax.grid(alpha=0.25)

    ax = axes[1][0]
    ax.plot(vol.rate_date, vol.vol_annualized * 100, color="#e8613c", lw=0.9)
    ax.set_title("Волатильность USD/RUB, 30 дней", fontsize=10, loc="left")
    ax.grid(alpha=0.25)

    ax = axes[1][1]
    ax.plot(index.month, index.deposit_index_norm, color="#8b5cf6", lw=1.6, label="вклад")
    ax.plot(index.month, index.fx_index, color="#2f6feb", lw=1.6, label="USD")
    ax.set_title("1 рубль: вклад vs доллар", fontsize=10, loc="left")
    ax.legend(frameon=False, fontsize=8)
    ax.grid(alpha=0.25)

    for row in axes:
        for ax in row:
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            ax.tick_params(labelsize=8)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    png_path = out_dir / "dashboard.png"
    fig.savefig(png_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    log.info("превью сохранено: %s", png_path)
