# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The shapes methods accept for nested request values, as typed dictionaries.

A plain ``dict`` literal satisfies them, and a type checker verifies its keys::

    client.customers.create(
        name="Acme",
        integrations={"attio": {"external_id": "rec_123"}},
    )

The builders in :mod:`kaitencloud.targeting` produce the feature flag ones.
"""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

from typing_extensions import Required, TypedDict

__all__ = [
    "BasicTargetingParam",
    "BasicVariantParam",
    "DefaultVariantParam",
    "IntegrationParam",
    "RolloutDateTargetingParam",
    "RolloutDateVariantParam",
    "RolloutPercentageTargetingParam",
    "RolloutPercentageVariantParam",
    "RolloutStepParam",
    "TargetingParam",
    "VariantParam",
]


class IntegrationParam(TypedDict, total=False):
    """A link from a customer or an instance to a record in a third-party system."""

    external_id: Required[str]
    """The record's identifier in the third-party system."""

    metadata: dict[str, Any]
    """Adapter-specific metadata."""

    web_url: str
    """An absolute http(s) link to the record."""

    last_error: str
    """The last synchronization error, if any."""


class VariantParam(TypedDict, total=False):
    """One possible value of a feature flag."""

    name: Required[str]
    value: Required[Any]
    description: str


class RolloutStepParam(TypedDict):
    """One end of a date-based rollout: a variant's share of traffic at a moment."""

    variant: str
    percentage: int
    date: str


class BasicVariantParam(TypedDict):
    """A default variant that always serves one variant."""

    type: Literal["basic"]
    value: str


class RolloutPercentageVariantParam(TypedDict):
    """A default variant that splits traffic between variants by weight."""

    type: Literal["rollout_percentage"]
    distribution: dict[str, int]


class RolloutDateVariantParam(TypedDict):
    """A default variant that shifts traffic between variants over a date range."""

    type: Literal["rollout_date"]
    start: RolloutStepParam
    end: RolloutStepParam


DefaultVariantParam: TypeAlias = (
    BasicVariantParam | RolloutPercentageVariantParam | RolloutDateVariantParam
)


class BasicTargetingParam(TypedDict):
    """A rule serving one variant to every context its CEL expression matches."""

    type: Literal["basic"]
    name: str
    rule: str
    variant: str


class RolloutPercentageTargetingParam(TypedDict):
    """A rule splitting the contexts it matches between variants by weight."""

    type: Literal["rollout_percentage"]
    name: str
    rule: str
    distribution: dict[str, int]


class RolloutDateTargetingParam(TypedDict):
    """A rule shifting the contexts it matches between variants over a date range."""

    type: Literal["rollout_date"]
    name: str
    rule: str
    start: RolloutStepParam
    end: RolloutStepParam


TargetingParam: TypeAlias = (
    BasicTargetingParam | RolloutPercentageTargetingParam | RolloutDateTargetingParam
)
