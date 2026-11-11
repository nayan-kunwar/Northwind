from __future__ import annotations

from decimal import Decimal

from .util import D


class RateTable:
    """FX rates with policy-compliant cross-rate derivation.

    A GBP rate that is not given directly is derived from two rates of the same
    type, e.g. GBP/INR closing = GBP/USD closing * USD/INR closing.
    """

    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rates: dict[tuple[str, str, str], Decimal] = {}
        for row in rows:
            self.rates[(row["base_currency"], row["quote_currency"], row["rate_type"])] = D(row["rate"])

    def direct(self, base: str, quote: str, rate_type: str) -> Decimal | None:
        if base == quote:
            return Decimal("1")
        return self.rates.get((base, quote, rate_type))

    def get(self, base: str, quote: str, rate_type: str) -> Decimal | None:
        if base == quote:
            return Decimal("1")
        direct = self.direct(base, quote, rate_type)
        if direct is not None:
            return direct
        for pivot in ("USD", "GBP", "INR", "SGD"):
            if pivot in (base, quote):
                continue
            first = self.direct(base, pivot, rate_type)
            second = self.direct(pivot, quote, rate_type)
            if first is not None and second is not None:
                return first * second
        return None

    def to_gbp(self, amount: Decimal, currency: str, rate_type: str) -> tuple[Decimal | None, Decimal | None]:
        """Return (amount_gbp, rate). rate is quote units per GBP."""
        if currency == "GBP":
            return amount, Decimal("1")
        rate = self.get("GBP", currency, rate_type)
        if rate is None:
            return None, None
        return amount / rate, rate

    @staticmethod
    def rate_type_for(entity: str, statement: str) -> str:
        if entity == "UK":
            return "identity"
        if entity == "US":
            return "average" if statement == "PL" else "closing"
        if entity == "IN":
            return "h2_average" if statement == "PL" else "closing"
        raise ValueError(entity)

    @staticmethod
    def rate_type_for_acquisition() -> str:
        return "spot"

    def describe_missing(self, currency: str, rate_type: str) -> str:
        if currency == "SGD":
            return (
                "No GBP/SGD closing rate and no USD/SGD rate to derive it; "
                "cannot retranslate at the closing rate."
            )
        return f"No {currency} {rate_type} rate available."
