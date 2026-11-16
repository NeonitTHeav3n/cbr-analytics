-- ============================================================
-- 02 · INTERMEDIATE
-- Здесь появляется смысл: календарь, «протяжка» курсов на выходные,
-- индекс рублёвого вклада по ключевой ставке, доходности и волатильность.
--
-- Зачем протягивать курс на выходные: ЦБ публикует курс только по рабочим
-- дням, а сравнивать «вклад vs валюта» нужно на одинаковых календарных датах,
-- иначе горизонты 30/90/365 дней съезжают.
-- ============================================================

-- Календарь непрерывным рядом от первого до последнего дня с данными
CREATE OR REPLACE TABLE int_calendar AS
SELECT CAST(gs AS DATE) AS calendar_date
FROM generate_series(
        (SELECT MIN(rate_date) FROM stg_currency_rates),
        (SELECT MAX(rate_date) FROM stg_currency_rates),
        INTERVAL 1 DAY
     ) AS t(gs);

-- Курс по каждому календарному дню (forward fill: последний известный курс)
CREATE OR REPLACE TABLE int_currency_daily AS
SELECT
    c.calendar_date AS rate_date,
    cur.char_code,
    (
        SELECT s.rub_per_unit
        FROM stg_currency_rates s
        WHERE s.char_code = cur.char_code
          AND s.rate_date <= c.calendar_date
        ORDER BY s.rate_date DESC
        LIMIT 1
    ) AS rub_per_unit
FROM int_calendar c
CROSS JOIN (SELECT DISTINCT char_code FROM stg_currency_rates) cur;

-- Ключевая ставка по каждому календарному дню
CREATE OR REPLACE TABLE int_key_rate_daily AS
SELECT
    c.calendar_date,
    (
        SELECT k.key_rate_pct
        FROM stg_key_rate k
        WHERE k.rate_date <= c.calendar_date
        ORDER BY k.rate_date DESC
        LIMIT 1
    ) AS key_rate_pct
FROM int_calendar c;

-- Индекс рублёвого депозита: 1 рубль, вложенный в первый день, под ставку,
-- начисляемую ежедневно (365 дней в году). Рост между датами d1 и d2
-- считается как deposit_index(d2) / deposit_index(d1).
CREATE OR REPLACE TABLE int_deposit_index AS
SELECT
    calendar_date,
    key_rate_pct,
    EXP(
        SUM(LN(1 + key_rate_pct / 100.0 / 365.0)) OVER (
            ORDER BY calendar_date
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        )
    ) AS deposit_index
FROM int_key_rate_daily
WHERE key_rate_pct IS NOT NULL;  -- первые дни диапазона могут быть раньше первого значения ставки

-- Дневные лог-доходности и годовая волатильность (окно скольжения — из config.yaml).
-- Важно: считаем ТОЛЬКО по дням, когда ЦБ реально публиковал курс. Если взять
-- календарь с протянутыми выходными, то 1/7 наблюдений будет с нулевой доходностью
-- и σ занизится примерно на 13%.
CREATE OR REPLACE TABLE int_fx_returns AS
WITH published AS (
    SELECT d.rate_date, d.char_code, d.rub_per_unit
    FROM int_currency_daily d
    JOIN stg_currency_rates s
      ON s.rate_date = d.rate_date
     AND s.char_code = d.char_code
),
daily AS (
    SELECT
        rate_date,
        char_code,
        rub_per_unit,
        LN(rub_per_unit) - LN(
            LAG(rub_per_unit) OVER (PARTITION BY char_code ORDER BY rate_date)
        ) AS log_return
    FROM published
)
SELECT
    rate_date,
    char_code,
    rub_per_unit,
    log_return,
    STDDEV_SAMP(log_return) OVER (
        PARTITION BY char_code
        ORDER BY rate_date
        ROWS BETWEEN {{vol_window_minus_one}} PRECEDING AND CURRENT ROW
    ) * SQRT({{annualization_days}}) AS vol_annualized
FROM daily;
