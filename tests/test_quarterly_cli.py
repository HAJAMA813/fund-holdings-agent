import datetime as dt

import pytest

from fund_holdings_agent.quarterly_cli import beijing_today, latest_closed_quarter, previous_quarter, quarter_label


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (dt.date(2026, 1, 1), dt.date(2025, 12, 31)),
        (dt.date(2026, 4, 1), dt.date(2026, 3, 31)),
        (dt.date(2026, 7, 1), dt.date(2026, 6, 30)),
        (dt.date(2026, 10, 1), dt.date(2026, 9, 30)),
    ],
)
def test_latest_closed_quarter(as_of, expected):
    assert latest_closed_quarter(as_of) == expected


def test_previous_quarter_and_label_cross_year():
    current = dt.date(2026, 3, 31)

    assert previous_quarter(current) == dt.date(2025, 12, 31)
    assert quarter_label(current) == "2026Q1"


def test_beijing_today_uses_asia_shanghai_boundary():
    utc_time = dt.datetime(2026, 6, 30, 16, 30, tzinfo=dt.timezone.utc)

    assert beijing_today(utc_time) == dt.date(2026, 7, 1)


def test_beijing_today_rejects_naive_datetime():
    with pytest.raises(ValueError, match="时区"):
        beijing_today(dt.datetime(2026, 7, 1, 0, 30))
