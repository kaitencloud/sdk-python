# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from typing import Any

from ..._utils import api_path
from ...types import (
    DefaultVariantParam,
    FeatureFlag,
    FeatureFlagType,
    ManifestEnvelope,
    ManifestFlag,
    TargetingParam,
    VariantParam,
)
from ._base import AsyncResource

__all__ = ["AsyncFeatureFlags"]


class AsyncFeatureFlags(AsyncResource):
    """Feature flags: variants, targeting rules and default variants.

    This namespace manages flag definitions. To evaluate a flag for a context, use
    ``client.flags``. The builders in :mod:`kaitencloud.targeting` write variants and rules.
    """

    async def list(self) -> builtins.list[FeatureFlag]:
        """Return every feature flag, walking all pages."""
        return await self._api.list_all("/feature-flags", FeatureFlag)

    async def get(self, feature_flag_slug: str) -> FeatureFlag:
        """Return the feature flag identified by ``feature_flag_slug``."""
        return await self._api.get(api_path("feature-flags", feature_flag_slug), FeatureFlag)

    async def create(
        self,
        *,
        name: str,
        type: FeatureFlagType,
        variants: Sequence[VariantParam],
        default_variant: str | DefaultVariantParam,
        targetings: Sequence[TargetingParam] = (),
        enabled: bool = True,
        description: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        event_name: str = "",
        slug: str | None = None,
    ) -> FeatureFlag:
        """Create a feature flag.

        Args:
            name: The flag's name.
            type: The type of its variants' values: ``boolean``, ``string``, ``number`` or
                ``object``.
            variants: Its possible values, e.g. ``[targeting.variant("on", True),
                targeting.variant("off", False)]``.
            default_variant: What it serves when no rule matches: a variant name, or a
                rollout from :func:`kaitencloud.targeting.split` or
                :func:`kaitencloud.targeting.schedule`.
            targetings: Its targeting rules, evaluated in order; the first match wins.
            enabled: The kill switch. A disabled flag serves its default variant to everyone
                and evaluates no rule.
            description: A description.
            metadata: Free-form metadata.
            event_name: The analytics event associated with the flag, if any.
            slug: Its URL-friendly identifier, generated when omitted. Doubles as the key the
                flag is evaluated by.
        """
        body = _flag(
            name=name,
            type=type,
            variants=variants,
            default_variant=default_variant,
            targetings=targetings,
            enabled=enabled,
            description=description,
            metadata=metadata,
            event_name=event_name,
        )
        if slug is not None:
            body["slug"] = slug
        return await self._api.send("POST", "/feature-flags", FeatureFlag, body=body)

    async def update(
        self,
        feature_flag_slug: str,
        *,
        name: str,
        type: FeatureFlagType,
        variants: Sequence[VariantParam],
        default_variant: str | DefaultVariantParam,
        targetings: Sequence[TargetingParam] = (),
        enabled: bool = True,
        description: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        event_name: str = "",
    ) -> None:
        """Replace a feature flag's definition.

        A full replacement: the variants, rules and metadata sent become the flag's whole
        definition. See :meth:`create` for what each field means.
        """
        body = _flag(
            name=name,
            type=type,
            variants=variants,
            default_variant=default_variant,
            targetings=targetings,
            enabled=enabled,
            description=description,
            metadata=metadata,
            event_name=event_name,
        )
        await self._api.send_empty("PUT", api_path("feature-flags", feature_flag_slug), body=body)

    async def delete(self, feature_flag_slug: str) -> None:
        """Delete the feature flag identified by ``feature_flag_slug``."""
        await self._api.send_empty("DELETE", api_path("feature-flags", feature_flag_slug))

    async def manifest(self) -> builtins.list[ManifestFlag]:
        """Return the OpenFeature manifest: every flag with its type and default value."""
        envelope = await self._api.get("/openfeature/v0/manifest", ManifestEnvelope)
        return builtins.list(envelope.flags or [])


def _flag(
    *,
    name: str,
    type: FeatureFlagType,
    variants: Sequence[VariantParam],
    default_variant: str | DefaultVariantParam,
    targetings: Sequence[TargetingParam],
    enabled: bool,
    description: str | None,
    metadata: Mapping[str, Any] | None,
    event_name: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "type": type,
        "variants": [
            {
                "name": variant["name"],
                "description": variant.get("description", ""),
                "value": variant["value"],
            }
            for variant in variants
        ],
        "default_variant": (
            {"type": "basic", "value": default_variant}
            if isinstance(default_variant, str)
            else dict(default_variant)
        ),
        "targetings": [dict(targeting) for targeting in targetings],
        "enabled": enabled,
        "description": description,
        "metadata": dict(metadata) if metadata is not None else {},
        "event_name": event_name,
    }
