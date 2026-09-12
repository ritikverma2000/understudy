from __future__ import annotations

import re
from dataclasses import dataclass


class MoneyParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedMoney:
    amount_cents: int
    currency: str


_USD_PATTERN = re.compile(
    r"^\s*"
    r"(?P<negative>-)?"
    r"\$"
    r"(?P<whole>(?:\d{1,3}(?:,\d{3})+|\d+))"
    r"\."
    r"(?P<fraction>\d{2})"
    r"\s*$"
)


def parse_money(
    text: str,
    *,
    locale: str,
    expected_currency: str,
) -> ParsedMoney:
    if locale != "en-US":
        raise MoneyParseError(f"unsupported locale {locale!r}")

    if expected_currency != "USD":
        raise MoneyParseError(
            f"unsupported currency {expected_currency!r}"
        )

    match = _USD_PATTERN.fullmatch(text)

    if match is None:
        # The source text is financial data. Keep it out of exceptions because
        # exception messages may be printed or persisted as failure evidence.
        raise MoneyParseError("invalid en-US money value")

    whole = int(match.group("whole").replace(",", ""))
    fraction = int(match.group("fraction"))
    amount_cents = whole * 100 + fraction

    if match.group("negative"):
        amount_cents = -amount_cents

    return ParsedMoney(
        amount_cents=amount_cents,
        currency="USD",
    )
