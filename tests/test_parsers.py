import pytest

from understudy.replay.parsers import (
    MoneyParseError,
    ParsedMoney,
    parse_money,
)


@pytest.mark.parametrize(
    ("text", "expected_cents"),
    [
        ("$1,250.50", 125050),
        ("$0.00", 0),
        ("$12.34", 1234),
        ("-$25.75", -2575),
        ("  $1,250.50  ", 125050),
    ],
)
def test_parse_en_us_money(
    text: str,
    expected_cents: int,
) -> None:
    assert parse_money(
        text,
        locale="en-US",
        expected_currency="USD",
    ) == ParsedMoney(
        amount_cents=expected_cents,
        currency="USD",
    )


@pytest.mark.parametrize(
    "text",
    [
        "$12,34.56",
        "$10",
        "1,250.50",
        "$1,250.5",
        "",
    ],
)
def test_rejects_malformed_money(text: str) -> None:
    with pytest.raises(MoneyParseError) as captured:
        parse_money(
            text,
            locale="en-US",
            expected_currency="USD",
        )

    if text:
        assert text not in str(captured.value)


def test_rejects_unsupported_locale() -> None:
    with pytest.raises(
        MoneyParseError,
        match="unsupported locale",
    ):
        parse_money(
            "$1,250.50",
            locale="de-DE",
            expected_currency="USD",
        )


def test_rejects_unsupported_currency() -> None:
    with pytest.raises(
        MoneyParseError,
        match="unsupported currency",
    ):
        parse_money(
            "$1,250.50",
            locale="en-US",
            expected_currency="EUR",
        )
