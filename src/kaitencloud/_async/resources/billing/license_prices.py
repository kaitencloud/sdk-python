# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from collections.abc import Mapping

from ...._utils import addon_quantities, api_path, compact, price_body
from ....types import (
    BillingModel,
    BillingPeriod,
    BillingTiming,
    InvoicePreview,
    Price,
    PriceStatus,
)
from .._base import AsyncResource

__all__ = ["AsyncBillingLicensePrices"]


class AsyncBillingLicensePrices(AsyncResource):
    """The prices of license versions.

    A ``FLAT_FEE`` price bills a subscription each period; a ``USAGE_BASED`` price bills the
    usage of an entitlement, and an ``OVERAGE`` price the usage above the license's limit, per
    sale unit. Amounts are decimal strings in minor units: ``"4900"`` is 49.00 in a currency
    with two decimals. The prices of a published version never change.
    """

    async def list(
        self,
        license_slug: str,
        *,
        status: PriceStatus | None = None,
        billing_model: BillingModel | None = None,
    ) -> builtins.list[Price]:
        """Return the prices of the license version, in display order; both statuses when omitted."""
        return await self._api.get_list(
            api_path("licenses", license_slug, "prices"),
            Price,
            params={"status": status, "billingModel": billing_model},
        )

    async def get(self, license_slug: str, price_id: str) -> Price:
        """Return one price of the license version."""
        return await self._api.get(api_path("licenses", license_slug, "prices", price_id), Price)

    async def create(
        self,
        license_slug: str,
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
        """Add a price to the license version, and return it.

        Args:
            license_slug: The license version.
            billing_model: ``FLAT_FEE``, ``USAGE_BASED`` or ``OVERAGE``.
            currency: An ISO 4217 code, upper case. One currency per version.
            unit_amount_decimal: The amount in minor units, as a decimal string: per period for
                ``FLAT_FEE``, per sale unit for a metered price.
            billing_period: ``MONTHLY``, ``QUARTERLY``, ``SEMI_ANNUAL`` or ``ANNUAL``. Required
                on a ``FLAT_FEE`` price, refused on a metered one.
            billing_timing: ``ADVANCE`` (the default for ``FLAT_FEE``) or ``ARREARS``, which a
                metered price must be.
            metered_entitlement_slug: The entitlement a metered price measures: granted by the
                version, with a reset period, aggregated by ``SUM`` or ``COUNT``.
            is_default: Make this ``FLAT_FEE`` price the default of its billing period.
            display_label: The invoice line's label.
            display_order: Its position among the version's prices.

        Raises:
            ConflictError: Another price is already the default of the period
                (``CreateLicensePrice.DefaultConflict``).
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
            "POST", api_path("licenses", license_slug, "prices"), Price, body=body
        )

    async def update(
        self,
        license_slug: str,
        price_id: str,
        *,
        unit_amount_decimal: str | None = None,
        billing_period: BillingPeriod | None = None,
        billing_timing: BillingTiming | None = None,
        metered_entitlement_slug: str | None = None,
        is_default: bool | None = None,
        display_label: str | None = None,
        display_order: int | None = None,
    ) -> Price:
        """Edit a price of a ``DRAFT`` version; what is omitted keeps its value.

        Its currency and billing model never change, and the prices of a published version are
        immutable (``UpdateLicensePrice.VersionNotDraft``).
        """
        body = compact(
            {
                "unitAmountDecimal": unit_amount_decimal,
                "billingPeriod": billing_period,
                "billingTiming": billing_timing,
                "meteredEntitlementSlug": metered_entitlement_slug,
                "isDefault": is_default,
                "displayLabel": display_label,
                "displayOrder": display_order,
            }
        )
        return await self._api.send(
            "PATCH", api_path("licenses", license_slug, "prices", price_id), Price, body=body
        )

    async def deprecate(self, license_slug: str, price_id: str) -> Price:
        """Retire a price from the catalog, for good.

        It keeps billing the subscriptions pinned to it, is no longer offered, and stops being a
        default.
        """
        return await self._api.send(
            "POST", api_path("licenses", license_slug, "prices", price_id, "deprecate"), Price
        )

    async def preview_invoice(
        self,
        license_slug: str,
        *,
        base_price_id: str | None = None,
        add_ons: Mapping[str, int] | None = None,
        sample_usage: Mapping[str, str] | None = None,
        instance_slug: str | None = None,
        voucher_code: str | None = None,
    ) -> InvoicePreview:
        """Compose the ``RENEWAL`` invoice a subscription to the version would get now.

        Nothing is written, and it works on a ``DRAFT`` version, to check its prices before
        publishing it.

        Args:
            license_slug: The license version.
            base_price_id: The ``FLAT_FEE`` price billed as the base. Defaults to the version's
                default one.
            add_ons: Add-on versions priced in, as ``{addon_slug: quantity}``.
            sample_usage: Usage of the metered entitlements over the period that ends, as
                ``{entitlement_slug: quantity}`` in decimal strings. An entitlement left out
                used nothing.
            instance_slug: Rate this instance's own usage instead of a sample.
            voucher_code: Apply a ``PRICE`` voucher's discount, consuming nothing.
        """
        body = compact(
            {
                "basePriceId": base_price_id,
                "addOns": addon_quantities(add_ons),
                "sampleUsage": (
                    [
                        {"entitlementSlug": slug, "quantity": quantity}
                        for slug, quantity in sample_usage.items()
                    ]
                    if sample_usage is not None
                    else None
                ),
                "instanceSlug": instance_slug,
                "voucherCode": voucher_code,
            }
        )
        return await self._api.send(
            "POST",
            api_path("licenses", license_slug, "invoice-preview"),
            InvoicePreview,
            body=body,
            idempotent=True,
        )
