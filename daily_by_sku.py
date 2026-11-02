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
    quantity: int | None
    price: int
    status: str


def parse_order(row: dict[str, str]) -> Order:
    values = {field: (row[field] or "").strip() for field in INPUT_FIELDS}
    status = STATUS_ALIASES.get(values["status"].lower())
    if status is None:
        raise DataError(f"unknown status {row['status']!r}")
    for field in ("order_id", "sku"):
        if not values[field]:
            raise DataError(f"empty {field}")

    # Пустое количество допустимо только у отменённых заказов: в выручку они
    # не входят, а в число заказов попадают. У выкупленного это ошибка данных.
    quantity = None
    if values["quantity"] or status == "delivered":
        quantity = _parse_int(values["quantity"], "quantity")
    try:
        order_date = date.fromisoformat(values["order_date"])
    except ValueError as exc:
        raise DataError(f"invalid order_date {values['order_date']!r}") from exc

    return Order(
        order_id=values["order_id"],
        order_date=order_date,
        sku=values["sku"],
        quantity=quantity,
        price=_parse_int(values["price"], "price"),
        status=status,
    )


def _parse_int(value: str, field: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise DataError(f"invalid {field} {value!r}") from exc
    if number < 0:
        raise DataError(f"negative {field} {value!r}")
    return number


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


def deduplicate(orders: list[Order]) -> tuple[list[Order], int]:
    """Оставляет по одной строке на order_id, возвращает заказы и число дублей.

    Дубль должен совпадать с первой строкой полностью (после нормализации).
    Если строки одного заказа расходятся, непонятно, какая верная, - падаем.
    """
    unique: dict[str, Order] = {}
    for order in orders:
        seen = unique.setdefault(order.order_id, order)
        if seen != order:
            raise DataError(f"order {order.order_id} has conflicting rows")
    return list(unique.values()), len(orders) - len(unique)


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
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", nargs="?", type=Path, default=Path("sales.csv"))
    parser.add_argument("-o", "--output", type=Path, default=Path("daily_by_sku.csv"))
    args = parser.parse_args(argv)

    try:
        orders, duplicates = deduplicate(read_orders(args.input))
    except (OSError, DataError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    rows = aggregate(orders)
    write_report(rows, args.output)
    print(
        f"{len(orders)} orders ({duplicates} duplicate rows skipped) "
        f"-> {len(rows)} rows in {args.output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
