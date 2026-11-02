"""Отчёт по заказам и выручке в разрезе «артикул - день» из выгрузки заказов.

Запуск: python daily_by_sku.py [sales.csv] [-o daily_by_sku.csv]
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

INPUT_FIELDS = ("order_id", "order_date", "sku", "quantity", "price", "status")
OUTPUT_FIELDS = ("sku", "order_date", "orders", "revenue")
# В выгрузке статусы встречаются в разном регистре и написании
# ("Delivered", "CANCELLED", "canceled"). Всё, чего нет в словаре, - ошибка,
# а не догадка.
STATUS_ALIASES = {
    "delivered": "delivered",
    "cancelled": "cancelled",
    "canceled": "cancelled",
}


class DataError(ValueError):
    """Строка выгрузки, которую нельзя однозначно интерпретировать."""


@dataclass(frozen=True)
class Order:
    order_id: str
    order_date: date
    sku: str
    quantity: int
    price: int
    status: str


def parse_order(row: dict[str, str]) -> Order:
    values = {field: (row[field] or "").strip() for field in INPUT_FIELDS}
    status = STATUS_ALIASES.get(values["status"].lower())
    if status is None:
        raise DataError(f"unknown status {row['status']!r}")
    try:
        return Order(
            order_id=values["order_id"],
            order_date=date.fromisoformat(values["order_date"]),
            sku=values["sku"],
            quantity=int(values["quantity"]),
            price=int(values["price"]),
            status=status,
        )
    except ValueError as exc:
        raise DataError(str(exc)) from exc


def read_orders(path: Path) -> list[Order]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = set(INPUT_FIELDS) - set(reader.fieldnames or ())
        if missing:
            raise DataError(f"{path}: missing columns {sorted(missing)}")
        orders = []
        for row in reader:
            try:
                orders.append(parse_order(row))
            except DataError as exc:
                raise DataError(f"{path}:{reader.line_num}: {exc}") from exc
    return orders


def aggregate(orders: list[Order]) -> list[dict[str, object]]:
    stats: dict[tuple[str, date], list[int]] = defaultdict(lambda: [0, 0])
    for order in orders:
        day = stats[(order.sku, order.order_date)]
        day[0] += 1
        if order.status == "delivered":
            day[1] += order.quantity * order.price
    return [
        {"sku": sku, "order_date": day.isoformat(), "orders": count, "revenue": revenue}
        for (sku, day), (count, revenue) in sorted(stats.items())
    ]


def write_report(rows: list[dict[str, object]], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", nargs="?", type=Path, default=Path("sales.csv"))
    parser.add_argument("-o", "--output", type=Path, default=Path("daily_by_sku.csv"))
    args = parser.parse_args(argv)

    try:
        orders = read_orders(args.input)
    except (OSError, DataError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rows = aggregate(orders)
    write_report(rows, args.output)
    print(f"{len(orders)} orders -> {len(rows)} rows in {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
