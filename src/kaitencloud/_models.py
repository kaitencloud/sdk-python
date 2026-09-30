# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The base class of every model the SDK returns."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

__all__ = ["KaitenModel"]


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
