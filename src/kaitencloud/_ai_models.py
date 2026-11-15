# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Compatibility aliases for the original AI response bridge, now contract-generated."""

from .types import AiCredits, AiUsageOutcome
from .types import EntitlementUsage as AiEntitlementUsage

__all__ = ["AiCredits", "AiEntitlementUsage", "AiUsageOutcome"]
