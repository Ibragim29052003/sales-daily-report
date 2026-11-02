from datetime import date

import pytest

from daily_by_sku import DataError, parse_order


def make_row(**overrides: str) -> dict[str, str]:
    row = {
        "order_id": "1000001",
        "order_date": "2026-09-14",
        "sku": "UYT-0001",
        "quantity": "2",
        "price": "790",
        "status": "delivered",
    }
    return row | overrides


def test_parses_valid_row():
    order = parse_order(make_row())

    assert order.order_id == "1000001"
    assert order.order_date == date(2026, 9, 14)
    assert order.quantity == 2
    assert order.price == 790
    assert order.status == "delivered"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("delivered", "delivered"),
        ("Delivered", "delivered"),
        ("DELIVERED", "delivered"),
        ("delivered ", "delivered"),
        ("cancelled", "cancelled"),
        ("CANCELLED", "cancelled"),
        ("canceled", "cancelled"),
    ],
)
def test_normalizes_status(raw, expected):
    assert parse_order(make_row(status=raw)).status == expected


@pytest.mark.parametrize("raw", ["", "returned", "deliverd"])
def test_rejects_unknown_status(raw):
    with pytest.raises(DataError, match="unknown status"):
        parse_order(make_row(status=raw))


def test_allows_missing_quantity_on_cancelled_order():
    assert parse_order(make_row(quantity="", status="cancelled")).quantity is None


def test_rejects_missing_quantity_on_delivered_order():
    with pytest.raises(DataError, match="invalid quantity"):
        parse_order(make_row(quantity=""))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("order_date", "2026-09-31", "invalid order_date"),
        ("order_date", "14.09.2026", "invalid order_date"),
        ("price", "abc", "invalid price"),
        ("quantity", "-1", "negative quantity"),
        ("order_id", " ", "empty order_id"),
        ("sku", "", "empty sku"),
    ],
)
def test_rejects_malformed_values(field, value, message):
    with pytest.raises(DataError, match=message):
        parse_order(make_row(**{field: value}))
