# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from typing import Any

from ..._utils import api_path
from ...types import Model, ModelModality, ModelStatus, VendorCosts
from ._base import AsyncResource

__all__ = ["AsyncModels"]


class AsyncModels(AsyncResource):
    """Organization model catalogue; costs are metadata, never SDK pricing."""

    async def list(
        self,
        *,
        status: ModelStatus | None = None,
        vendor: str | None = None,
        modality: ModelModality | None = None,
        limit: int | None = None,
    ) -> builtins.list[Model]:
        """Walk catalogue pages, optionally capped at ``limit`` models."""
        return await self._api.list_all(
            "/models",
            Model,
            params={"status": status, "vendor": vendor, "modality": modality},
            limit=limit,
        )

    async def get(self, model_slug: str) -> Model:
        return await self._api.get(api_path("models", model_slug), Model)

    async def create(
        self,
        *,
        name: str,
        slug: str,
        vendor: str,
        modality: ModelModality,
        status: ModelStatus = "ACTIVE",
        description: str = "",
        external_ids: Sequence[str] = (),
        vendor_costs: VendorCosts | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Model:
        body: dict[str, Any] = {
            "name": name,
            "slug": slug,
            "vendor": vendor,
            "modality": modality,
            "status": status,
            "description": description,
            "externalIds": list(external_ids),
            "metadata": dict(metadata or {}),
        }
        if vendor_costs is not None:
            body["vendorCosts"] = vendor_costs.to_dict()
        return await self._api.send("POST", "/models", Model, body=body)

    async def update(
        self,
        model_slug: str,
        *,
        name: str,
        vendor: str,
        modality: ModelModality,
        status: ModelStatus = "ACTIVE",
        description: str = "",
        external_ids: Sequence[str] = (),
        vendor_costs: VendorCosts | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> Model:
        """Full replacement; slug and modality must remain unchanged."""
        body: dict[str, Any] = {
            "name": name,
            "slug": model_slug,
            "vendor": vendor,
            "modality": modality,
            "status": status,
            "description": description,
            "externalIds": list(external_ids),
            "metadata": dict(metadata or {}),
        }
        if vendor_costs is not None:
            body["vendorCosts"] = vendor_costs.to_dict()
        return await self._api.send("PUT", api_path("models", model_slug), Model, body=body)

    async def delete(self, model_slug: str) -> None:
        """Delete a model; the server refuses models referenced by conversion rules."""
        await self._api.request("DELETE", api_path("models", model_slug))
