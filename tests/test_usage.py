# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The enforcement arithmetic, on the boundaries the API refuses reports at."""

from __future__ import annotations

import pytest

from kaitencloud import UNLIMITED, usage


def test_a_hard_limit_caps_usage_at_its_value() -> None:
    assert usage.maximum_allowed_usage(100, 0) == 100
    assert usage.is_hard_limit(100, 0)
    assert not usage.is_soft_limit(100, 0)
    assert usage.accepts(100, 100, 0)
    assert not usage.accepts(100, 101, 0)


def test_a_soft_limit_tolerates_its_overage_percent() -> None:
    assert usage.maximum_allowed_usage(100, 10) == 110
    assert usage.is_soft_limit(100, 10)
    assert usage.accepts(100, 105, 10)
    assert usage.accepts(100, 110, 10)
    assert not usage.accepts(100, 110.5, 10)


def test_an_unlimited_grant_has_no_cap() -> None:
    assert usage.is_unlimited(UNLIMITED)
    assert usage.maximum_allowed_usage(UNLIMITED, -1) is None
    assert usage.remaining(UNLIMITED, 10**9, -1) is None
    assert usage.percentage_used(UNLIMITED, 10**9) is None
    assert usage.accepts(UNLIMITED, 10**12, -1)
    assert not usage.is_hard_limit(UNLIMITED, -1)
    assert not usage.is_soft_limit(UNLIMITED, -1)


def test_zero_is_a_real_cap() -> None:
    assert usage.maximum_allowed_usage(0, 0) == 0
    assert not usage.accepts(0, 1, 0)
    assert usage.remaining(0, 0, 0) == 0


def test_remaining_counts_down_to_the_cap_not_to_the_value() -> None:
    assert usage.remaining(100, 105, 10) == 5
    assert usage.remaining(100, 120, 10) == 0


def test_percentage_used_is_measured_against_the_value_and_can_pass_100() -> None:
    assert usage.percentage_used(100, 80) == 80
    assert usage.percentage_used(100, 105) == pytest.approx(105)
    assert usage.percentage_used(0, 0) is None


def test_a_missing_overage_percent_reads_as_a_hard_limit() -> None:
    assert usage.maximum_allowed_usage(30, None) == 30
    assert usage.is_hard_limit(30, None)
