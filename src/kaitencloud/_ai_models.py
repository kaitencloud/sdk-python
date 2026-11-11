# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Compatibility aliases for the original AI response bridge, now contract-generated."""

from .types import (
    AiCredits,
    AiInference,
    AiInferencePricing,
    AiInferenceRefund,
    AiUsageOutcome,
    AiUsageRule,
    AiVendorCost,
    OrganizationAiInference,
)
from .types import ReportedEntitlementUsage as AiEntitlementUsage

__all__ = [
    "AiCredits",
    "AiEntitlementUsage",
    "AiInference",
    "AiInferencePricing",
    "AiInferenceRefund",
    "AiUsageOutcome",
    "AiUsageRule",
    "AiVendorCost",
    "OrganizationAiInference",
]
