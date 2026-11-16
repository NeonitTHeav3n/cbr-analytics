"""CLI: python -m cbr_analytics <команда>."""

from __future__ import annotations

import argparse
import sys

from cbr_analytics.config import load_config
from cbr_analytics.http import setup_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cbr-analytics",
        description="ETL + витрины по данным ЦБ РФ: курсы валют и ключевая ставка.",
    )
    parser.add_argument("--config", default=None, help="путь к config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_extract = sub.add_parser("extract", help="скачать сырые данные ЦБ в data/raw")
    p_extract.add_argument("--force", action="store_true", help="перекачать даже закэшированное")

    sub.add_parser("build", help="пересобрать витрины из уже скачанных данных")
    sub.add_parser("report", help="собрать HTML-дашборд из витрин")

    p_all = sub.add_parser("all", help="extract + build + report (полный прогон)")
    p_all.add_argument("--force", action="store_true", help="перекачать даже закэшированное")
    return parser


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)

    # импортируем здесь, чтобы `--help` работал без pandas/duckdb
    from cbr_analytics.pipeline import run_all, run_build, run_extract

    if args.command == "extract":
        run_extract(cfg, force=args.force)
    elif args.command == "build":
        data = run_extract(cfg, force=False)  # данные берутся из кэша data/raw
        run_build(cfg, data)
    elif args.command == "report":
        from cbr_analytics.report.dashboard import build_report

        warehouse = run_build(cfg, run_extract(cfg))
        build_report(warehouse, cfg)
    elif args.command == "all":
        warehouse = run_all(cfg, force=args.force)
        from cbr_analytics.report.dashboard import build_report

        build_report(warehouse, cfg)
        warehouse.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
