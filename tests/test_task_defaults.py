"""Timezone and duration inference regressions."""

import pytest

from custom_components.todoist_enhanced.models import MetadataSnapshot, normalize_task


def task(**fields):
    return normalize_task(
        {"id": "fixture", **fields},
        MetadataSnapshot.build([], [], []),
        "America/New_York",
    )


@pytest.mark.parametrize(
    "labels,amount,source",
    [
        (["15M"], 15, "label"),
        (["1D"], 1440, "label"),
        (["1.5hr"], 90, "label"),
        (["1HR", "60M"], 60, "label"),
        (["15M", "30M"], None, "ambiguous"),
        (["0M", "-1HR", "task15M", "15M_extra"], None, "unknown"),
    ],
)
def test_duration_labels(labels, amount, source):
    result = task(labels=labels)
    assert result["duration"] is None
    assert result["labels"] == labels
    assert result["duration_source"] == source
    assert result["effective_duration"] == (
        {"amount": amount, "unit": "minute"} if amount else None
    )


def test_native_wins():
    result = task(duration={"amount": 20, "unit": "minute"}, labels=["1HR"])
    assert result["effective_duration"] == result["duration"]
    assert result["duration_source"] == "native"


@pytest.mark.parametrize(
    "date,zone,effective,source,floating",
    [
        ("2026-09-20T22:00:00", None, "America/New_York", "default", True),
        ("2026-09-20T22:00:00Z", None, "+0000", "offset", False),
        ("2026-09-20T22:00:00", "Europe/London", "Europe/London", "todoist", False),
        ("2026-09-20", None, "America/New_York", "default", False),
    ],
)
def test_timezones(date, zone, effective, source, floating):
    due = task(due={"date": date, "timezone": zone})["due"]
    assert due["timezone"] == zone
    assert due["effective_timezone"] == effective
    assert due["timezone_source"] == source
    assert due["is_floating"] == floating
    if "T" not in date:
        assert due["datetime"] is None
