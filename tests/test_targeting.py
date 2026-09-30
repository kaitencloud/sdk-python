# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The feature flag builders produce the shapes the contract describes."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaitencloud import targeting

START = datetime(2026, 9, 14, tzinfo=timezone.utc)


def test_variants_and_default_variants() -> None:
    assert targeting.variant("on", True) == {"name": "on", "value": True, "description": ""}
    assert targeting.fixed("off") == {"type": "basic", "value": "off"}
    assert targeting.split({"on": 20, "off": 80}) == {
        "type": "rollout_percentage",
        "distribution": {"on": 20, "off": 80},
    }
    assert targeting.schedule(
        start=targeting.step("on", 0, START), end=targeting.step("on", 100, "2026-10-14T00:00:00Z")
    ) == {
        "type": "rollout_date",
        "start": {"variant": "on", "percentage": 0, "date": "2026-09-14T00:00:00Z"},
        "end": {"variant": "on", "percentage": 100, "date": "2026-10-14T00:00:00Z"},
    }


def test_rules() -> None:
    assert targeting.rule("Growth", "__kaiten.license.slug == 'growth'", "on") == {
        "type": "basic",
        "name": "Growth",
        "rule": "__kaiten.license.slug == 'growth'",
        "variant": "on",
    }
    assert targeting.split_rule("Rollout", "true", {"on": 1, "off": 3})["type"] == (
        "rollout_percentage"
    )
    rule = targeting.schedule_rule(
        "Launch", "true", start=targeting.step("on", 0, START), end=targeting.step("on", 100, START)
    )
    assert (rule["type"], rule["name"]) == ("rollout_date", "Launch")


@pytest.mark.parametrize(
    "distribution",
    [{}, {"on": 0, "off": 100}, {"on": -5}, {"on": 2.5}, {"on": True}],
    ids=["empty", "zero weight", "negative", "fractional", "boolean"],
)
def test_a_split_needs_positive_integer_weights(distribution: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="split"):
        targeting.split(distribution)  # type: ignore[arg-type]


@pytest.mark.parametrize("percentage", [-1, 101])
def test_a_step_percentage_is_between_0_and_100(percentage: int) -> None:
    with pytest.raises(ValueError, match="percentage"):
        targeting.step("on", percentage, START)
