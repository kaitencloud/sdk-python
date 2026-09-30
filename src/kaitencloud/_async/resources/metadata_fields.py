# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from typing import Any

from ..._utils import api_path, compact
from ...types import MetadataField, MetadataFieldImpact, MetadataResourceType
from ._base import AsyncResource

__all__ = ["AsyncMetadataFields"]


class AsyncMetadataFields(AsyncResource):
    """Metadata fields: the typed fields your organization declares on instances and zones.

    Each field is a JSON Schema. The metadata of an instance or a deployment zone is validated
    against the active fields declared for its resource type.
    """

    async def list(self, resource_type: MetadataResourceType) -> builtins.list[MetadataField]:
        """Return the metadata fields declared for ``resource_type``, walking all pages."""
        return await self._api.list_all(
            "/metadata-fields", MetadataField, params={"resourceType": resource_type}
        )

    async def create(
        self,
        *,
        resource_type: MetadataResourceType,
        key: str,
        label: str,
        json_schema: Mapping[str, Any],
        display_order: int | None = None,
    ) -> MetadataField:
        """Declare a metadata field.

        Args:
            resource_type: ``INSTANCE`` or ``DEPLOYMENT_ZONE``. Immutable.
            key: The metadata key the field describes, e.g. ``"region"``. Unique among the
                active fields of the resource type, and immutable.
            label: The label the console shows.
            json_schema: A JSON Schema 2020-12 document for the value, e.g.
                ``{"type": "string", "enum": ["eu", "us"]}``.
            display_order: Its position in the console. Afterwards only :meth:`reorder`
                changes it.
        """
        body = {
            "resourceType": resource_type,
            "key": key,
            "label": label,
            "jsonSchema": dict(json_schema),
            **compact({"displayOrder": display_order}),
        }
        return await self._api.send("POST", "/metadata-fields", MetadataField, body=body)

    async def update(
        self,
        field_id: str,
        *,
        resource_type: MetadataResourceType,
        key: str,
        label: str,
        json_schema: Mapping[str, Any],
    ) -> MetadataField:
        """Change a metadata field's label and schema, and return the field.

        ``resource_type`` and ``key`` are immutable: send the stored values back, as the API
        requires them and refuses different ones. Preview what a stricter schema would
        invalidate with :meth:`dry_run` first.
        """
        body = {
            "resourceType": resource_type,
            "key": key,
            "label": label,
            "jsonSchema": dict(json_schema),
        }
        return await self._api.send(
            "PATCH", api_path("metadata-fields", field_id), MetadataField, body=body
        )

    async def archive(self, field_id: str) -> MetadataField:
        """Archive a metadata field, which frees its key for a new one."""
        return await self._api.send(
            "POST", api_path("metadata-fields", field_id, "archive"), MetadataField
        )

    async def unarchive(self, field_id: str) -> MetadataField:
        """Restore an archived metadata field."""
        return await self._api.send(
            "POST", api_path("metadata-fields", field_id, "unarchive"), MetadataField
        )

    async def dry_run(self, field_id: str, json_schema: Mapping[str, Any]) -> MetadataFieldImpact:
        """Preview what a candidate schema would invalidate, without changing anything.

        Returns how many existing resources hold a value the candidate schema would refuse,
        with a few of them as samples.
        """
        return await self._api.send(
            "POST",
            api_path("metadata-fields", field_id, "dry-run"),
            MetadataFieldImpact,
            body={"jsonSchema": dict(json_schema)},
            idempotent=True,
        )

    async def reorder(self, field_ids: Sequence[str]) -> None:
        """Set the display order of metadata fields to the order of ``field_ids``."""
        await self._api.send_empty(
            "POST", "/metadata-fields/reorder", body={"ids": list(field_ids)}, idempotent=True
        )
