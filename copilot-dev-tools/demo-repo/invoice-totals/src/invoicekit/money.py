"""Money helpers."""


def round_money(value: float) -> float:
    """Round an amount to the cent."""
    return round(value, 2)


def format_money(value: float, currency: str = "EUR") -> str:
    return f"{round_money(value):,.2f} {currency}"
