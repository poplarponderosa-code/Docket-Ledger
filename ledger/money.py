"""Money: currencies, formatting and invoice arithmetic. No Qt in here.

All amounts are Decimal and every line, discount and tax is rounded to the currency's cents
(half up), so the PDF always adds up exactly as printed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# code -> (symbol, decimals, name)
CURRENCIES: dict[str, tuple[str, int, str]] = {
    "CAD": ("$", 2, "Canadian dollar"),
    "USD": ("$", 2, "US dollar"),
    "EUR": ("€", 2, "Euro"),
    "GBP": ("£", 2, "Pound sterling"),
    "AUD": ("$", 2, "Australian dollar"),
    "NZD": ("$", 2, "New Zealand dollar"),
    "CHF": ("CHF ", 2, "Swiss franc"),
    "JPY": ("¥", 0, "Japanese yen"),
    "INR": ("₹", 2, "Indian rupee"),
    "MXN": ("$", 2, "Mexican peso"),
    "BRL": ("R$", 2, "Brazilian real"),
    "ZAR": ("R", 2, "South African rand"),
    "SEK": ("kr ", 2, "Swedish krona"),
    "NOK": ("kr ", 2, "Norwegian krone"),
    "DKK": ("kr ", 2, "Danish krone"),
    "PLN": ("zł ", 2, "Polish zloty"),
    "SGD": ("$", 2, "Singapore dollar"),
    "HKD": ("$", 2, "Hong Kong dollar"),
    "PHP": ("₱", 2, "Philippine peso"),
}

ZERO = Decimal("0")


def dec(value, default: Decimal | None = ZERO) -> Decimal | None:
    """Reads a number a person typed ("1,240.50", "$75", " 12 ")."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return default
    text = str(value).strip().replace(",", "").replace("$", "").replace(" ", "")
    for sym in ("€", "£", "¥", "₹", "₱", "R$", "kr", "CHF", "zł"):
        text = text.replace(sym, "")
    if not text:
        return default
    try:
        return Decimal(text)
    except InvalidOperation:
        return default


def decimals(currency: str) -> int:
    return CURRENCIES.get(currency, ("", 2, ""))[1]


def quantize(amount: Decimal, currency: str = "CAD") -> Decimal:
    q = Decimal(1).scaleb(-decimals(currency))
    return amount.quantize(q, rounding=ROUND_HALF_UP)


def fmt_money(amount: Decimal, currency: str = "CAD", code: bool = False) -> str:
    sym, places, _ = CURRENCIES.get(currency, ("", 2, ""))
    amount = quantize(amount, currency)
    neg = amount < 0
    text = f"{abs(amount):,.{places}f}"
    out = f"{'-' if neg else ''}{sym}{text}"
    if not sym:
        out = f"{out} {currency}"
    elif code:
        out = f"{out} {currency}"
    return out


def fmt_number(value: Decimal, places: int = 2) -> str:
    """1.50, 3, 2.25 — trailing zeros kept to `places` but whole numbers stay whole."""
    value = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    if value == value.to_integral():
        return f"{value:,.0f}"
    return f"{value:,.{places}f}"


def hours_from_seconds(seconds: int) -> Decimal:
    return (Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---- invoice arithmetic ----------------------------------------------------------------------------
@dataclass
class Line:
    kind: str                            # hours | fixed | qty
    description: str
    detail: str = ""                     # small text under the description
    category: str = ""
    qty: Decimal = ZERO                  # hours for "hours", count for "qty"
    unit: str = ""
    price: Decimal | None = None         # rate per hour / per unit; the amount for "fixed"
    unpriced: bool = False

    @property
    def amount(self) -> Decimal:
        if self.price is None:
            return ZERO
        if self.kind == "fixed":
            return self.price
        return self.qty * self.price


@dataclass
class TaxAmount:
    name: str
    rate: Decimal
    amount: Decimal


@dataclass
class Totals:
    currency: str
    lines: list[Line]
    subtotal: Decimal
    discount_label: str
    discount: Decimal
    taxes: list[TaxAmount] = field(default_factory=list)
    total: Decimal = ZERO
    unpriced: list[str] = field(default_factory=list)


def compute(lines: list[Line], currency: str, discount_kind: str = "none", discount_value=None,
            taxes: list[tuple[str, Decimal]] | None = None) -> Totals:
    """Subtotal, discount, taxes and total, each rounded to the currency."""
    subtotal = sum((quantize(ln.amount, currency) for ln in lines), ZERO)
    dv = dec(discount_value) or ZERO
    if discount_kind == "percent" and dv:
        discount = quantize(subtotal * dv / Decimal(100), currency)
        label = f"Discount ({fmt_number(dv)}%)"
    elif discount_kind == "amount" and dv:
        discount = quantize(min(dv, subtotal), currency)
        label = "Discount"
    else:
        discount, label = ZERO, ""
    taxable = subtotal - discount
    tax_out = [TaxAmount(name, rate, quantize(taxable * rate / Decimal(100), currency))
               for name, rate in (taxes or []) if rate]
    total = taxable + sum((t.amount for t in tax_out), ZERO)
    return Totals(currency, lines, subtotal, label, discount, tax_out, total,
                  [ln.description for ln in lines if ln.unpriced])
