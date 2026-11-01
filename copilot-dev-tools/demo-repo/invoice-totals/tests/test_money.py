import pytest

from invoicekit.money import format_money, round_money


@pytest.mark.parametrize("value,expected", [
    (10.0, 10.0),
    (3.14159, 3.14),
    (2.675, 2.68),
    (0.125, 0.13),
    (20.625, 20.63),
])
def test_round_money_half_up(value, expected):
    assert round_money(value) == expected


def test_format_money():
    assert format_money(1234.5) == "1,234.50 EUR"
