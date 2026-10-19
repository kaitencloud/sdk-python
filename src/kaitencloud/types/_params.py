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

from decimal import Decimal
from typing import Any, Literal, TypeAlias

from typing_extensions import Required, TypedDict

from ._core import AiUnitType

__all__ = [
    "AiUsageParam",
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


class AiUsageParam(TypedDict, total=False):
    """What an AI call consumed -- or, on a reservation, what it is expected to.

    The token counts are disjoint: ``input_tokens`` is the input neither read from nor written
    to a cache, so the call's whole input is the sum of the three input fields. The normalisers
    in :mod:`kaitencloud.ai` build one from a provider's own usage object.
    """

    input_tokens: int
    """Input tokens neither read from nor written to a cache."""

    cache_read_input_tokens: int
    """Input tokens served from the provider's cache."""

    cache_write_input_tokens: int
    """Input tokens written to the provider's cache."""

    output_tokens: int
    """Output tokens, reasoning included."""

    units: str | int | Decimal
    """Generated units -- images, seconds, frames -- counted by ``unit_type``."""

    unit_type: AiUnitType
    """What ``units`` counts."""

    duration_ms: int
    """The billable duration, in milliseconds."""
