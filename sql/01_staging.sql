-- ============================================================
-- 01 · STAGING
-- Слой «как есть»: приводим типы и имена, никакой бизнес-логики.
-- ============================================================

CREATE OR REPLACE TABLE stg_currency_rates AS
SELECT
    CAST(rate_date   AS DATE)    AS rate_date,
    CAST(char_code   AS VARCHAR) AS char_code,
    CAST(nominal     AS INTEGER) AS nominal,
    CAST(rate_per_unit AS DOUBLE) AS rub_per_unit
FROM raw_currency_rates;

CREATE OR REPLACE TABLE stg_key_rate AS
SELECT
    CAST(rate_date   AS DATE)   AS rate_date,
    CAST(key_rate_pct AS DOUBLE) AS key_rate_pct
FROM raw_key_rate;
