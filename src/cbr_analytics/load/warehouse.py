"""Load: запись в хранилище и выполнение SQL-витрин.

Два движка, один и тот же SQL:
* duckdb   — файл на диске, ноль настройки, режим по умолчанию (и режим CI);
* postgres — docker-compose, нужен, если хочется подключить Metabase/Superset.

SQL в sql/ написан в переносимом подмножестве ANSI, поэтому файлы витрин
не дублируются под каждый движок.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pandas as pd

from cbr_analytics.config import LoadConfig
from cbr_analytics.http import get_logger

log = get_logger(__name__)

CREATE_RE = re.compile(r"CREATE\s+OR\s+REPLACE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w.]+)", re.I)


def _pg_type(dtype) -> str:
    """Тип колонки pandas -> тип Postgres (хватает для наших данных)."""
    kind = getattr(dtype, "kind", "O")
    return {
        "i": "BIGINT",
        "f": "DOUBLE PRECISION",
        "b": "BOOLEAN",
        "M": "TIMESTAMP",
        "O": "TEXT",
    }.get(kind, "TEXT")


class Warehouse:
    """Тонкая обёртка над соединением: загрузить DataFrame, прогнать SQL, прочитать результат."""

    def __init__(self, cfg: LoadConfig):
        self.cfg = cfg
        self.engine = cfg.engine.lower()
        self._conn = None

    # --- соединение -------------------------------------------------
    def connect(self):
        if self._conn is not None:
            return self._conn
        if self.engine == "duckdb":
            Path(self.cfg.duckdb_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(self.cfg.duckdb_path)
        elif self.engine == "postgres":
            import psycopg  # опциональная зависимость

            if not self.cfg.db_url:
                raise ValueError("для engine=postgres нужен DB_URL")
            self._conn = psycopg.connect(self.cfg.db_url, autocommit=True)
        else:
            raise ValueError(f"неизвестный engine: {self.engine}")
        log.info("подключение: %s", self.engine)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Warehouse:
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # --- операции ---------------------------------------------------
    def execute(self, sql: str) -> None:
        conn = self.connect()
        if self.engine == "duckdb":
            conn.execute(sql)
            return
        for statement in self._adapt_for_postgres(sql):
            if statement.strip():
                conn.execute(statement)

    def load_dataframe(self, df: pd.DataFrame, table: str) -> None:
        """Полная перезапись таблицы. Идемпотентно: повторный запуск даёт тот же результат."""
        conn = self.connect()
        if self.engine == "duckdb":
            conn.register("_load_batch", df)  # noqa: F821 — register() не типизирован
            conn.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM _load_batch")
            conn.unregister("_load_batch")
            return

        from psycopg import sql as pgsql

        column_types = ", ".join(f"{col} {_pg_type(dtype)}" for col, dtype in df.dtypes.items())
        conn.execute(pgsql.SQL("DROP TABLE IF EXISTS {}").format(pgsql.Identifier(table)))
        conn.execute(
            pgsql.SQL("CREATE TABLE {} ({})").format(
                pgsql.Identifier(table), pgsql.SQL(column_types)
            )
        )
        placeholders = ", ".join(["%s"] * len(df.columns))
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {table} VALUES ({placeholders})",
                [
                    tuple(None if pd.isna(v) else v for v in row)
                    for row in df.itertuples(index=False)
                ],
            )

    @staticmethod
    def render_sql(sql: str, params: dict[str, object] | None = None) -> str:
        """Подставляет {{placeholder}} из конфига — параметры не хардкодим в SQL."""
        for key, value in (params or {}).items():
            sql = sql.replace("{{" + key + "}}", str(value))
        leftover = re.findall(r"\{\{\s*(\w+)\s*\}\}", sql)
        if leftover:
            raise ValueError(f"в SQL остались незаполненные placeholder'ы: {leftover}")
        return sql

    def run_sql_file(self, path: Path, params: dict[str, object] | None = None) -> None:
        sql = self.render_sql(Path(path).read_text(encoding="utf-8"), params)
        log.info("выполняю %s", Path(path).name)
        self.execute(sql)

    def run_sql_dir(self, directory: Path, params: dict[str, object] | None = None) -> list[Path]:
        """Выполняет все *.sql в директории в алфавитном порядке."""
        files = sorted(Path(directory).glob("*.sql"))
        for path in files:
            self.run_sql_file(path, params)
        return files

    def query(self, sql: str) -> pd.DataFrame:
        conn = self.connect()
        if self.engine == "duckdb":
            return conn.execute(sql).fetch_df()
        import psycopg.rows

        with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql)
            return pd.DataFrame(cur.fetchall())

    # --- диалект ----------------------------------------------------
    @staticmethod
    def _adapt_for_postgres(sql: str) -> list[str]:
        """Postgres не умеет CREATE OR REPLACE TABLE — разворачиваем в DROP + CREATE."""
        statements: list[str] = []
        for chunk in sql.split(";"):
            match = CREATE_RE.search(chunk)
            if match:
                statements.append(f"DROP TABLE IF EXISTS {match.group(1)}")
                chunk = CREATE_RE.sub(f"CREATE TABLE {match.group(1)}", chunk)
            statements.append(chunk)
        return statements
