# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from typing import Any, Literal

from ...._types import EntitlementValueInput
from ...._utils import api_path, compact, entitlement_value, price_body
from ....types import (
    Addon,
    AddonEntitlement,
    AddonFamily,
    AddonLifecycleState,
    BillingModel,
    BillingPeriod,
    BillingTiming,
    CompatibleLicenseFamilies,
    IncreaseBilling,
    OverrideBehavior,
    Price,
    PriceStatus,
    PricingType,
)
from .._base import AsyncResource

__all__ = ["AsyncBillingAddons"]


class AsyncBillingAddons(AsyncResource):
    """The add-on catalog: what an instance can hold on top of its license, by the unit.

    Add-ons are versioned like licenses: an add-on *family* is the product, each version has
    its grants and its prices, and moves through ``DRAFT``, ``PUBLISHED`` and ``ARCHIVED``. A
    version fits the license families :meth:`set_compatibility` names, and none until then.
    """

    async def list(
        self,
        *,
        lifecycle_state: AddonLifecycleState | None = None,
        family_slug: str | None = None,
    ) -> builtins.list[Addon]:
        """Return the organization's add-on versions, newest first, walking all pages.

        Args:
            lifecycle_state: Only versions in this state.
            family_slug: Only versions of this family.
        """
        return await self._api.list_all(
            "/addons",
            Addon,
            params={"lifecycleState": lifecycle_state, "familySlug": family_slug},
        )

    async def get(self, addon_slug: str) -> Addon:
        """Return the add-on version identified by ``addon_slug``."""
        return await self._api.get(api_path("addons", addon_slug), Addon)

    async def create(
        self,
        *,
        name: str,
        pricing_type: PricingType,
        description: str = "",
        slug: str | None = None,
        family_slug: str | None = None,
        family_id: str | None = None,
        version_name: str | None = None,
        lifecycle_state: Literal["DRAFT", "PUBLISHED"] | None = None,
        is_default: bool | None = None,
        max_quantity: int | None = None,
        increase_billing: IncreaseBilling | None = None,
    ) -> Addon:
        """Create an add-on version: the first of a new family, or the next of an existing one.

        Args:
            name: The add-on's name, e.g. ``"Extra seats"``.
            pricing_type: ``FREE``, ``PAID`` or ``CUSTOM``.
            description: A description.
            slug: The version's slug. Defaults to ``<family>-v<n>`` for a new version of a
                family, and to one generated from the name for a new family.
            family_slug: Make this a new version of this family.
            family_id: The same family, by identifier.
            version_name: A label for the version. Defaults to ``"Version - <n>"``.
            lifecycle_state: ``DRAFT``, or ``PUBLISHED`` when omitted.
            is_default: Make this version its family's default.
            max_quantity: The largest quantity an instance can hold.
            increase_billing: Read only when this opens a new family: how a mid-period increase
                of its add-ons billed in advance is billed, ``TRUE_UP`` (the default) or
                ``NEXT_BOUNDARY``.
        """
        body = {
            "name": name,
            "description": description,
            "pricingType": pricing_type,
            **compact(
                {
                    "slug": slug,
                    "familySlug": family_slug,
                    "familyId": family_id,
                    "versionName": version_name,
                    "lifecycleState": lifecycle_state,
                    "isDefault": is_default,
                    "maxQuantity": max_quantity,
                    "increaseBilling": increase_billing,
                }
            ),
        }
        return await self._api.send("POST", "/addons", Addon, body=body)

    async def update(
        self,
        addon_slug: str,
        *,
        name: str,
        description: str = "",
        is_default: bool = False,
        version_name: str | None = None,
        max_quantity: int | None = None,
    ) -> Addon:
        """Replace an add-on version's name, description, version name, default flag and maximum.

        A full replacement, as for a license version: its family, pricing type and state are
        not part of it.
        """
        body = {
            "name": name,
            "description": description,
            "isDefault": is_default,
            **compact({"versionName": version_name, "maxQuantity": max_quantity}),
        }
        return await self._api.send("PUT", api_path("addons", addon_slug), Addon, body=body)

    async def delete(self, addon_slug: str) -> None:
        """Delete an add-on version that was never attached and grants nothing.

        Its family goes with its last version.

        Raises:
            ConflictError: The version is in use (``DeleteAddon.InUseConflict``).
        """
        await self._api.send_empty("DELETE", api_path("addons", addon_slug))

    async def publish(self, addon_slug: str) -> Addon:
        """Put a ``DRAFT`` version on sale, and return it ``PUBLISHED``."""
        return await self._api.send("POST", api_path("addons", addon_slug, "publish"), Addon)

    async def archive(self, addon_slug: str) -> Addon:
        """Withdraw a ``PUBLISHED`` version from sale: instances holding it keep it."""
        return await self._api.send("POST", api_path("addons", addon_slug, "archive"), Addon)

    async def unarchive(self, addon_slug: str) -> Addon:
        """Put an ``ARCHIVED`` version back on sale, and return it ``PUBLISHED``."""
        return await self._api.send("POST", api_path("addons", addon_slug, "unarchive"), Addon)

    async def list_compatibility(self, addon_slug: str) -> CompatibleLicenseFamilies:
        """Return the license families an instance must be on to attach this version.

        None means it cannot be attached at all.
        """
        return await self._api.get(
            api_path("addons", addon_slug, "compatible-license-families"),
            CompatibleLicenseFamilies,
        )

    async def set_compatibility(self, addon_slug: str, family_slug: str) -> None:
        """Let instances on any version of the license family attach this add-on version."""
        await self._api.send_empty(
            "PUT", api_path("addons", addon_slug, "compatible-license-families", family_slug)
        )

    async def remove_compatibility(self, addon_slug: str, family_slug: str) -> None:
        """Stop the license family attaching this version; instances holding it keep it."""
        await self._api.send_empty(
            "DELETE", api_path("addons", addon_slug, "compatible-license-families", family_slug)
        )

    async def list_entitlements(self, addon_slug: str) -> builtins.list[AddonEntitlement]:
        """Return what the add-on version grants per unit of quantity."""
        return await self._api.get_list(
            api_path("addons", addon_slug, "entitlements"), AddonEntitlement
        )

    async def get_entitlement(self, addon_slug: str, entitlement_slug: str) -> AddonEntitlement:
        """Return one grant of the add-on version."""
        return await self._api.get(
            api_path("addons", addon_slug, "entitlements", entitlement_slug), AddonEntitlement
        )

    async def assign_entitlement(
        self,
        addon_slug: str,
        entitlement_slug: str,
        value: EntitlementValueInput,
        *,
        override_behavior: OverrideBehavior | None = None,
        overage_percent: int | None = None,
    ) -> AddonEntitlement:
        """Grant an entitlement per unit of the add-on version, and return the grant.

        Args:
            addon_slug: The add-on version that grants.
            entitlement_slug: The entitlement granted.
            value: What one unit grants, as for a license grant: a ``bool``, a number, or a
                mapping for a CONFIG entitlement. A number counts once per unit held.
            override_behavior: How a number grant combines with the license's: ``ADD``,
                ``OVERRIDE`` or ``MAX``.
            overage_percent: The overage the add-on allows: ``-1`` with an unlimited value,
                ``0`` or more otherwise. Omitted, it inherits the license grant's.

        Raises:
            ConflictError: An instance with a live subscription holds the version
                (``AssignAddonEntitlement.BillingActive``).
        """
        body = {
            "entitlementSlug": entitlement_slug,
            **_grant(value, override_behavior, overage_percent),
        }
        return await self._api.send(
            "POST", api_path("addons", addon_slug, "entitlements"), AddonEntitlement, body=body
        )

    async def update_entitlement(
        self,
        addon_slug: str,
        entitlement_slug: str,
        value: EntitlementValueInput,
        *,
        override_behavior: OverrideBehavior | None = None,
        overage_percent: int | None = None,
    ) -> AddonEntitlement:
        """Replace a grant's value, override behavior and overage: see :meth:`assign_entitlement`."""
        return await self._api.send(
            "PUT",
            api_path("addons", addon_slug, "entitlements", entitlement_slug),
            AddonEntitlement,
            body=_grant(value, override_behavior, overage_percent),
        )

    async def unassign_entitlement(self, addon_slug: str, entitlement_slug: str) -> None:
        """Remove a grant from the add-on version.

        Raises:
            ConflictError: An instance with a live subscription holds the version, or an
                ``ACTIVE`` price of the version meters the entitlement.
        """
        await self._api.send_empty(
            "DELETE", api_path("addons", addon_slug, "entitlements", entitlement_slug)
        )

    async def list_prices(
        self, addon_slug: str, *, status: PriceStatus | None = None
    ) -> builtins.list[Price]:
        """Return the prices of the add-on version, in display order; both statuses when omitted."""
        return await self._api.get_list(
            api_path("addons", addon_slug, "prices"), Price, params={"status": status}
        )

    async def create_price(
        self,
        addon_slug: str,
        *,
        billing_model: BillingModel,
        currency: str,
        unit_amount_decimal: str,
        billing_period: BillingPeriod | None = None,
        billing_timing: BillingTiming | None = None,
        metered_entitlement_slug: str | None = None,
        is_default: bool | None = None,
        display_label: str | None = None,
        display_order: int | None = None,
    ) -> Price:
        """Add a price to the add-on version, under the rules of a license price.

        A price never changes once created: create another and deprecate this one. See
        :meth:`AsyncBillingLicensePrices.create` for the arguments.
        """
        body = price_body(
            billing_model=billing_model,
            currency=currency,
            unit_amount_decimal=unit_amount_decimal,
            billing_period=billing_period,
            billing_timing=billing_timing,
            metered_entitlement_slug=metered_entitlement_slug,
            is_default=is_default,
            display_label=display_label,
            display_order=display_order,
        )
        return await self._api.send(
            "POST", api_path("addons", addon_slug, "prices"), Price, body=body
        )

    async def deprecate_price(self, addon_slug: str, price_id: str) -> Price:
        """Stop offering a price of the add-on version.

        Raises:
            ConflictError: It is a default price (``DeprecateAddonPrice.IsDefault``), which bills
                every instance holding the version: retire it through a new version.
        """
        return await self._api.send(
            "POST", api_path("addons", addon_slug, "prices", price_id, "deprecate"), Price
        )

    async def list_families(self) -> builtins.list[AddonFamily]:
        """Return every add-on family with its versions, newest family first."""
        return await self._api.get_list("/addon-families", AddonFamily)

    async def get_family(self, family_slug: str) -> AddonFamily:
        """Return an add-on family with its versions and its current version."""
        return await self._api.get(api_path("addon-families", family_slug), AddonFamily)

    async def update_family(
        self,
        family_slug: str,
        *,
        is_public: bool | None = None,
        increase_billing: IncreaseBilling | None = None,
    ) -> AddonFamily:
        """Change an add-on family's own settings; what is omitted keeps its value.

        Args:
            family_slug: The family.
            is_public: List the family's default ``PUBLISHED`` version, with its ``ACTIVE``
                prices, in the public catalog. Families are private until made public.
            increase_billing: How a mid-period increase of its add-ons billed in advance is
                billed, from the next composition: ``TRUE_UP`` or ``NEXT_BOUNDARY``.
        """
        body = compact({"isPublic": is_public, "increaseBilling": increase_billing})
        return await self._api.send(
            "PATCH", api_path("addon-families", family_slug), AddonFamily, body=body
        )


def _grant(
    value: EntitlementValueInput,
    override_behavior: OverrideBehavior | None,
    overage_percent: int | None,
) -> dict[str, Any]:
    return {
        "value": entitlement_value(value),
        **compact(
            {
                "overrideBehavior": override_behavior,
                "limitCapExceededOveragePercent": overage_percent,
            }
        ),
    }
