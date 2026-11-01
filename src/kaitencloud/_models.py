# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The base class of every model the SDK returns, and the results it composes from them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from .types import ReportedEntitlementUsage

__all__ = ["KaitenModel", "UsageReportResult"]


class KaitenModel(BaseModel):
    """Base class of every model the SDK returns.

    Models are lenient where the API grows. A field added to the API after this release is
    kept rather than rejected -- read it from :attr:`model_extra` -- and an enum value the SDK
    does not know yet parses as a plain string.

    Attributes are snake_case. :meth:`to_dict` and :meth:`to_json` give back the exact wire
    shape, camelCase keys included, which is what to send when echoing a resource back.
    """

    model_config = ConfigDict(
        extra="allow",
        validate_by_alias=True,
        validate_by_name=True,
        serialize_by_alias=True,
    )

    def to_dict(self) -> dict[str, Any]:
        """Return the model as the API spells it: JSON-compatible values, wire key names."""
        return self.model_dump(mode="json", by_alias=True, exclude_unset=True)

    def to_json(self, *, indent: int | None = None) -> str:
        """Return the model as a JSON document, with wire key names."""
        return self.model_dump_json(by_alias=True, exclude_unset=True, indent=indent)


@dataclass(frozen=True)
class UsageReportResult:
    """What a usage report answered: the usage it results in, and what the API said about it."""

    usage: ReportedEntitlementUsage
    """The entitlement's usage after the report. On a replay, the earlier report's answer: it
    may describe a usage window that has closed since, so do not read it as the current gauge.
    """

    replayed: bool
    """The report repeated one already accepted under its ``transaction_id``, and nothing was
    counted again."""

    metadata_dropped: bool
    """The report's metadata was above 4 KiB and was not stored. The report itself counted."""
