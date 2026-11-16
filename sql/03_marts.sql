-- ============================================================
-- 03 · MARTS (витрины под конкретные вопросы дашборда)
-- Каждая витрина отвечает на один вопрос. Лишних колонок не тащим.
-- ============================================================

-- ---------- 1. Курс и ставка по месяцам -----------------------
-- Вопрос: что происходило с курсом и ставкой, как они связаны?
CREATE OR REPLACE TABLE mart_fx_monthly AS
WITH eom AS (
    SELECT
        DATE_TRUNC('month', rate_date) AS month,
        char_code,
        rub_per_unit,
        ROW_NUMBER() OVER (
            PARTITION BY DATE_TRUNC('month', rate_date), char_code
            ORDER BY rate_date DESC
        ) AS rn
    FROM int_currency_daily
),
monthly_agg AS (
    SELECT
        DATE_TRUNC('month', rate_date) AS month,
        char_code,
        AVG(rub_per_unit) AS rate_avg,
        MIN(rub_per_unit) AS rate_min,
        MAX(rub_per_unit) AS rate_max
    FROM int_currency_daily
    GROUP BY 1, 2
),
monthly_fx AS (
    SELECT
        e.month,
        e.char_code,
        e.rub_per_unit AS rate_end_of_month,
        a.rate_avg,
        a.rate_min,
        a.rate_max
    FROM eom e
    JOIN monthly_agg a ON a.month = e.month AND a.char_code = e.char_code
    WHERE e.rn = 1
),
monthly_rate AS (
    SELECT DATE_TRUNC('month', calendar_date) AS month, AVG(key_rate_pct) AS key_rate_avg
    FROM int_key_rate_daily
    GROUP BY 1
)
SELECT
    f.month,
    f.char_code,
    f.rate_end_of_month,
    f.rate_avg,
    f.rate_min,
    f.rate_max,
    f.rate_end_of_month / LAG(f.rate_end_of_month) OVER (
        PARTITION BY f.char_code ORDER BY f.month
    ) - 1 AS mom_change,
    r.key_rate_avg
FROM monthly_fx f
LEFT JOIN monthly_rate r ON r.month = f.month;

-- ---------- 2. Волатильность ----------------------------------
-- Вопрос: когда рубль был «дёрганым» и насколько?
CREATE OR REPLACE TABLE mart_volatility AS
SELECT
    rate_date,
    char_code,
    rub_per_unit,
    log_return,
    vol_annualized
FROM int_fx_returns
WHERE vol_annualized IS NOT NULL;

-- ---------- 3. Вклад vs валюта --------------------------------
-- Главный вопрос проекта: если бы у меня были деньги на дату X и горизонт H,
-- что дало бы больше в рублях — рублёвый вклад под ключевую ставку
-- или покупка валюты и держание?
CREATE OR REPLACE TABLE mart_deposit_vs_fx AS
WITH horizons AS (
    SELECT * FROM (VALUES {{horizons_values}}) AS t(horizon_days)
),
pairs AS (
    SELECT
        f.rate_date AS start_date,
        h.horizon_days,
        f.char_code,
        f.rub_per_unit                                       AS fx_start,
        fe.rub_per_unit                                      AS fx_end,
        d2.deposit_index / d1.deposit_index                  AS deposit_factor
    FROM int_currency_daily f
    JOIN horizons h ON 1 = 1
    JOIN int_currency_daily fe
        ON fe.rate_date = f.rate_date + h.horizon_days
       AND fe.char_code = f.char_code
    JOIN int_deposit_index d1 ON d1.calendar_date = f.rate_date
    JOIN int_deposit_index d2 ON d2.calendar_date = f.rate_date + h.horizon_days
)
SELECT
    start_date,
    start_date + horizon_days          AS end_date,
    horizon_days,
    char_code,
    fx_start,
    fx_end,
    fx_end / fx_start - 1              AS fx_return,
    deposit_factor - 1                 AS deposit_return,
    (deposit_factor - 1) - (fx_end / fx_start - 1) AS diff_pp,
    CASE WHEN deposit_factor > fx_end / fx_start THEN 1 ELSE 0 END AS deposit_won
FROM pairs;

-- ---------- 4. Сводка по горизонтам ---------------------------
-- Вопрос: на каком горизонте вклад выигрывает чаще и насколько стабильно?
CREATE OR REPLACE TABLE mart_headline AS
SELECT
    horizon_days,
    char_code,
    COUNT(*)                                        AS n_observations,
    AVG(deposit_won)                                AS deposit_win_share,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY diff_pp)  AS diff_pp_median,
    percentile_cont(0.1) WITHIN GROUP (ORDER BY diff_pp)  AS diff_pp_p10,
    percentile_cont(0.9) WITHIN GROUP (ORDER BY diff_pp)  AS diff_pp_p90,
    percentile_cont(0.5) WITHIN GROUP (ORDER BY fx_return) AS fx_return_median,
    STDDEV_SAMP(fx_return)                          AS fx_return_std
FROM mart_deposit_vs_fx
GROUP BY horizon_days, char_code;

-- ---------- 5. Индекс: 1 вложенный рубль ----------------------
-- Вопрос: как выглядит накопленный результат «вклад» vs «валюта» с общей точки старта?
CREATE OR REPLACE TABLE mart_monthly_index AS
WITH months AS (
    SELECT DISTINCT DATE_TRUNC('month', calendar_date) AS month FROM int_calendar
),
eom AS (
    SELECT
        DATE_TRUNC('month', calendar_date) AS month,
        MAX(calendar_date)                 AS calendar_date
    FROM int_calendar
    GROUP BY 1
),
fx AS (
    SELECT e.month, c.char_code, c.rub_per_unit
    FROM eom e
    JOIN int_currency_daily c ON c.rate_date = e.calendar_date
),
dep AS (
    SELECT e.month, d.deposit_index
    FROM eom e
    JOIN int_deposit_index d ON d.calendar_date = e.calendar_date
),
combined AS (
    SELECT
        f.month,
        f.char_code,
        f.rub_per_unit   AS fx_rate,
        d.deposit_index
    FROM fx f
    JOIN dep d ON d.month = f.month
)
SELECT
    month,
    char_code,
    fx_rate,
    deposit_index,
    fx_rate / FIRST_VALUE(fx_rate) OVER (PARTITION BY char_code ORDER BY month) AS fx_index,
    deposit_index / FIRST_VALUE(deposit_index) OVER (ORDER BY month)             AS deposit_index_norm
FROM combined
WHERE month >= (SELECT MIN(month) FROM months);

-- ---------- 6. Коридор на горизонте (не прогноз!) -------------
-- Вопрос: какой разброс курса «нормален» на месяц вперёд при текущей волатильности?
-- Это НЕ предсказание: это коридор ±1.96σ из исторической волатильности,
-- то есть базовый уровень «а что если ничего не изменится».
CREATE OR REPLACE TABLE mart_forecast_band AS
WITH last_obs AS (
    SELECT char_code, MAX(rate_date) AS rate_date
    FROM mart_volatility
    GROUP BY char_code
)
SELECT
    v.char_code,
    v.rate_date                                              AS as_of_date,
    v.rub_per_unit                                           AS spot,
    v.vol_annualized,
    v.rub_per_unit * EXP(-1.96 * v.vol_annualized * SQRT({{forecast_horizon}} / 365.0)) AS band_low_95,
    v.rub_per_unit * EXP( 1.96 * v.vol_annualized * SQRT({{forecast_horizon}} / 365.0)) AS band_high_95
FROM mart_volatility v
JOIN last_obs l ON l.char_code = v.char_code AND l.rate_date = v.rate_date;
