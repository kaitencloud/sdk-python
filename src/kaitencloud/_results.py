# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Results that carry more than a response body."""

from __future__ import annotations

from dataclasses import dataclass

from .types import EntitlementUsage

__all__ = ["UsageReportResult"]


@dataclass(frozen=True)
class UsageReportResult:
    """What an accepted usage report answers.

    Attributes:
        usage: The entitlement's usage after the report.
        replayed: The report carried a ``transaction_id`` the API had already accepted:
            ``usage`` is that report's original answer and nothing was counted again. It may
            describe a usage window that has since closed, so do not read it as the current
            gauge.
        metadata_dropped: The metadata was above 4 KiB and was not stored. The report itself
            was counted.
    """

    usage: EntitlementUsage
    replayed: bool
    metadata_dropped: bool
