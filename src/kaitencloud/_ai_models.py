# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The answer to an AI usage report, written by hand until the contract carries it.

Every other model is generated from ``openapi/openapi.yaml``. These three describe the members
the AI credits contract adds to ``EntitlementUsage`` -- ``reserved`` and ``ai`` -- and are
isolated here so that the regenerated ``EntitlementUsage`` and ``AiUsageOutcome`` replace them
with no change elsewhere: delete this module and import from :mod:`kaitencloud.types`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from ._models import KaitenModel
from .types import EntitlementUsage

__all__ = ["AiCredits", "AiEntitlementUsage", "AiUsageOutcome"]


class AiCredits(KaitenModel):
    """Credits an AI usage report moved, as decimal strings with at most six decimals."""

    reserved: str | None = None
    """What a reservation set aside, or what a commit closed."""

    computed: str | None = None
    """What the conversion rule priced the call at, before its policy and guardrails."""

    charged: str | None = None
    """What the commit charged the pool."""


class AiUsageOutcome(KaitenModel):
    """What an AI usage report did, next to the usage it leaves the pool at."""

    transaction_id: str = Field(alias="transactionId")
    """The report's transaction id, echoed."""

    phase: Literal["reserve", "commit"] | str
    """The phase reported."""

    status: Literal["RESERVED", "COMMITTED", "RELEASED"] | str
    """The operation's status after this report."""

    credits: AiCredits = Field(default_factory=AiCredits)
    """The credits this report reserved, computed or charged."""

    remaining: str | None = None
    """Credits left: the limit, minus usage, minus open reservations. ``None`` when unlimited,
    negative when overdrawn."""

    expires_at: datetime | None = Field(default=None, alias="expiresAt")
    """When the reservation lapses. Reservations only."""

    authorized: bool | None = None
    """Commits only: ``False`` when no rule priced the call, or the model is unknown or
    archived."""

    warnings: list[str] = Field(default_factory=list)
    """``MODEL_DEPRECATED``, ``ESTIMATE_INCOMPLETE``, ``CONVERSION_INPUT_MISSING``,
    ``RESERVATION_EXPIRED``, ``OVERDRAWN``, ``MODEL_NOT_AUTHORIZED``, ``UNKNOWN_MODEL``."""


class AiEntitlementUsage(EntitlementUsage):
    """An entitlement's usage after an AI usage report, with what the report did."""

    reserved: str | None = None
    """Credits held by the pool's open, unexpired reservations, as a decimal string."""

    ai: AiUsageOutcome | None = None
    """What the AI usage report did."""
