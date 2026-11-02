"""Независимая сверка daily_by_sku.csv с расчётом на SQL.

Скрипт не импортирует daily_by_sku.py: выгрузка грузится в sqlite как есть,
очистка и агрегация повторены на SQL. Если оба способа дают одинаковый
результат, ошибка в одном из них маловероятна.

Запуск: python checks/crosscheck.py [sales.csv] [daily_by_sku.csv]
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

NORMALIZED_ORDERS = """
CREATE TABLE orders AS
SELECT DISTINCT
    trim(order_id) AS order_id,
    trim(order_date) AS order_date,
    trim(sku) AS sku,
    CAST(nullif(trim(quantity), '') AS INTEGER) AS quantity,
    CAST(trim(price) AS INTEGER) AS price,
    CASE lower(trim(status)) WHEN 'canceled' THEN 'cancelled' ELSE lower(trim(status)) END
        AS status
FROM raw
"""

EXPECTED_REPORT = """
SELECT
    sku,
    order_date,
    count(*) AS orders,
    coalesce(sum(CASE WHEN status = 'delivered' THEN quantity * price END), 0) AS revenue
FROM orders
GROUP BY sku, order_date
ORDER BY sku, order_date
"""


def load_csv(db: sqlite3.Connection, table: str, path: Path) -> None:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        columns = ", ".join(header)
        placeholders = ", ".join("?" * len(header))
        db.execute(f"CREATE TABLE {table} ({columns})")
        db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", reader)


def scalar(db: sqlite3.Connection, sql: str) -> int:
    return db.execute(sql).fetchone()[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sales", nargs="?", type=Path, default=Path("sales.csv"))
    parser.add_argument("report", nargs="?", type=Path, default=Path("daily_by_sku.csv"))
    args = parser.parse_args(argv)

    db = sqlite3.connect(":memory:")
    load_csv(db, "raw", args.sales)
    load_csv(db, "report", args.report)
    db.execute(NORMALIZED_ORDERS)

    print("Выгрузка:")
    print(f"  строк:                      {scalar(db, 'SELECT count(*) FROM raw')}")
    print(f"  уникальных заказов:         {scalar(db, 'SELECT count(*) FROM orders')}")
    nonstandard = "SELECT count(*) FROM raw WHERE status NOT IN ('delivered', 'cancelled')"
    print(f"  нестандартных статусов:     {scalar(db, nonstandard)}")
    empty_qty = "SELECT count(*) FROM raw WHERE trim(quantity) = ''"
    print(f"  пустых quantity:            {scalar(db, empty_qty)}")

    # Строки, отличающиеся только записью статуса, схлопываются в DISTINCT.
    # Если после этого order_id всё равно повторяется - строки противоречат друг другу.
    conflicts = scalar(db, "SELECT count(*) - count(DISTINCT order_id) FROM orders")
    if conflicts:
        print(f"FAIL: {conflicts} заказов с противоречивыми строками")
        return 1

    expected = [tuple(map(str, row)) for row in db.execute(EXPECTED_REPORT)]
    actual = list(db.execute("SELECT sku, order_date, orders, revenue FROM report"))

    print("Контрольные суммы (SQL / отчёт):")
    print(f"  строк:   {len(expected)} / {len(actual)}")
    for name, index in (("orders", 2), ("revenue", 3)):
        totals = [sum(int(row[index]) for row in rows) for rows in (expected, actual)]
        print(f"  {name}: {totals[0]} / {totals[1]}")

    # Сравниваем списки целиком, поэтому порядок строк тоже проверяется.
    if expected != actual:
        diff = [(e, a) for e, a in zip(expected, actual, strict=False) if e != a][:5]
        print(f"FAIL: отчёт расходится с SQL-расчётом, первые различия: {diff}")
        return 1

    print("OK: отчёт совпадает с SQL-расчётом построчно")
    return 0


if __name__ == "__main__":
    sys.exit(main())
