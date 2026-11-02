import csv
from datetime import date

import pytest

from daily_by_sku import DataError, Order, aggregate, deduplicate, main


def make_order(order_id="1", day=1, sku="UYT-0001", quantity=1, price=100, status="delivered"):
    return Order(order_id, date(2026, 9, day), sku, quantity, price, status)


def test_deduplicate_keeps_one_row_per_order():
    order = make_order()
    other = make_order(order_id="2")

    unique, duplicates = deduplicate([order, other, order])

    assert unique == [order, other]
    assert duplicates == 1


def test_deduplicate_rejects_conflicting_rows():
    with pytest.raises(DataError, match="order 1 has conflicting rows"):
        deduplicate([make_order(quantity=1), make_order(quantity=2)])


def test_aggregate_counts_cancelled_orders_but_not_their_revenue():
    rows = aggregate(
        [
            make_order("1", quantity=2, price=790),
            make_order("2", quantity=1, price=790),
            make_order("3", quantity=3, price=790, status="cancelled"),
        ]
    )

    assert rows == [{"sku": "UYT-0001", "order_date": "2026-09-01", "orders": 3, "revenue": 2370}]


def test_aggregate_keeps_days_with_only_cancelled_orders():
    rows = aggregate([make_order(quantity=None, status="cancelled")])

    assert rows == [{"sku": "UYT-0001", "order_date": "2026-09-01", "orders": 1, "revenue": 0}]


def test_aggregate_sorts_by_sku_then_date():
    rows = aggregate(
        [
            make_order("1", day=2, sku="UYT-0002"),
            make_order("2", day=3, sku="UYT-0001"),
            make_order("3", day=1, sku="UYT-0002"),
            make_order("4", day=1, sku="UYT-0001"),
        ]
    )

    assert [(r["sku"], r["order_date"]) for r in rows] == [
        ("UYT-0001", "2026-09-01"),
        ("UYT-0001", "2026-09-03"),
        ("UYT-0002", "2026-09-01"),
        ("UYT-0002", "2026-09-02"),
    ]


def test_main_writes_report_from_dirty_export(tmp_path):
    source = tmp_path / "sales.csv"
    source.write_text(
        "order_id,order_date,sku,quantity,price,status\n"
        "1,2026-09-02,UYT-0002,1,690,delivered\n"
        "2,2026-09-01,UYT-0001,2,790,Delivered\n"
        "2,2026-09-01,UYT-0001,2,790,delivered \n"  # тот же заказ, другая запись статуса
        "3,2026-09-01,UYT-0001,,790,canceled\n"
        "4,2026-09-01,UYT-0001,1,790,DELIVERED\n",
        encoding="utf-8",
    )
    target = tmp_path / "daily_by_sku.csv"

    assert main([str(source), "-o", str(target)]) == 0

    with target.open(encoding="utf-8", newline="") as f:
        assert list(csv.reader(f)) == [
            ["sku", "order_date", "orders", "revenue"],
            ["UYT-0001", "2026-09-01", "3", "2370"],
            ["UYT-0002", "2026-09-02", "1", "690"],
        ]


def test_main_reports_line_number_of_bad_row(tmp_path, capsys):
    source = tmp_path / "sales.csv"
    source.write_text(
        "order_id,order_date,sku,quantity,price,status\n"
        "1,2026-09-01,UYT-0001,1,790,delivered\n"
        "2,2026-09-01,UYT-0001,1,790,returned\n",
        encoding="utf-8",
    )
    target = tmp_path / "daily_by_sku.csv"

    assert main([str(source), "-o", str(target)]) == 1
    assert f"{source}:3: unknown status 'returned'" in capsys.readouterr().err
    assert not target.exists()


def test_main_rejects_export_without_required_columns(tmp_path, capsys):
    source = tmp_path / "sales.csv"
    source.write_text("order_id,order_date,sku\n1,2026-09-01,UYT-0001\n", encoding="utf-8")

    assert main([str(source), "-o", str(tmp_path / "out.csv")]) == 1
    assert "missing columns ['price', 'quantity', 'status']" in capsys.readouterr().err
