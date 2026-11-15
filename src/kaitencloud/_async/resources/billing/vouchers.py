# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from ...._utils import api_path, check_limit, compact, optional_datetime
from ....types import (
    DiscountAppliesTo,
    DiscountType,
    Redemption,
    RedemptionRulesParam,
    Validity,
    Voucher,
    VoucherDuration,
    VoucherGrantParam,
    VoucherStatus,
    VoucherType,
)
from .._base import AsyncResource

__all__ = ["AsyncBillingVouchers"]


class AsyncBillingVouchers(AsyncResource):
    """The organization's vouchers: codes that discount a price or boost entitlements.

    A ``PRICE`` voucher discounts a subscription's invoices; an ``ENTITLEMENT_BOOST`` changes
    entitlements while it applies; a ``FLAG_GRANT`` serves flag variants; a ``COMPOSITE`` does
    several. A voucher is created ``DRAFT`` and becomes redeemable once published.
    """

    async def list(
        self,
        *,
        status: VoucherStatus | None = None,
        voucher_type: Literal["PRICE", "ENTITLEMENT_BOOST"] | None = None,
        restricted_customer_slug: str | None = None,
    ) -> builtins.list[Voucher]:
        """Return the organization's vouchers, newest first, with their codes, walking all pages."""
        return await self._api.list_all(
            "/vouchers",
            Voucher,
            params={
                "status": status,
                "voucherType": voucher_type,
                "restrictedCustomerSlug": restricted_customer_slug,
            },
        )

    async def get(self, voucher_id: str) -> Voucher:
        """Return a voucher, with its code."""
        return await self._api.get(api_path("vouchers", voucher_id), Voucher)

    async def create(
        self,
        *,
        name: str,
        voucher_type: VoucherType,
        duration: VoucherDuration,
        code: str | None = None,
        description: str | None = None,
        duration_in_periods: int | None = None,
        starts_at: datetime | str | None = None,
        expires_at: datetime | str | None = None,
        max_redemptions: int | None = None,
        restricted_customer_slug: str | None = None,
        price_discount_type: DiscountType | None = None,
        price_discount_value: str | None = None,
        currency: str | None = None,
        price_applies_to: DiscountAppliesTo | None = None,
        applicable_license_ids: Sequence[str] | None = None,
        applicable_license_price_ids: Sequence[str] | None = None,
        applicable_addon_ids: Sequence[str] | None = None,
        applicable_addon_price_ids: Sequence[str] | None = None,
        grants: Sequence[VoucherGrantParam] | None = None,
        flag_grants: Mapping[str, str] | None = None,
        redemption_rules: RedemptionRulesParam | None = None,
    ) -> Voucher:
        """Create a ``DRAFT`` voucher, and return it with its code.

        Args:
            name: The voucher's name.
            voucher_type: ``PRICE``, ``ENTITLEMENT_BOOST``, ``FLAG_GRANT`` or ``COMPOSITE``.
            duration: How long a discount lasts: ``ONE_TIME``, ``REPEATING`` or ``FOREVER``.
            code: 8 to 64 of ``[A-Za-z0-9_-]``, matched without case or separators. Generated
                when omitted.
            description: A description.
            duration_in_periods: How many periods a ``REPEATING`` discount lasts.
            starts_at: When it can be redeemed from.
            expires_at: When it can no longer be redeemed.
            max_redemptions: How many times it can be redeemed.
            restricted_customer_slug: The only customer that may redeem it.
            price_discount_type: ``PERCENTAGE`` or ``FIXED_AMOUNT``.
            price_discount_value: A percentage in (0, 100], or an amount in minor units, as a
                string.
            currency: Required with ``FIXED_AMOUNT``, refused otherwise.
            price_applies_to: What the discount applies to: ``LICENSE_BASE``, ``ADDONS``,
                ``BOTH``, or ``SELECTED_PRICES``.
            applicable_license_ids: The license versions it applies to.
            applicable_license_price_ids: With ``SELECTED_PRICES``, the license prices.
            applicable_addon_ids: The add-on versions it applies to.
            applicable_addon_price_ids: With ``SELECTED_PRICES``, the add-on prices.
            grants: What an ``ENTITLEMENT_BOOST`` grants, one entitlement each.
            flag_grants: What a ``FLAG_GRANT`` serves, as ``{flag_slug: variant}``.
            redemption_rules: Who may redeem it, beyond its dates and count.
        """
        body = _voucher(
            name=name,
            voucher_type=voucher_type,
            duration=duration,
            code=code,
            description=description,
            duration_in_periods=duration_in_periods,
            starts_at=starts_at,
            expires_at=expires_at,
            max_redemptions=max_redemptions,
            restricted_customer_slug=restricted_customer_slug,
            price_discount_type=price_discount_type,
            price_discount_value=price_discount_value,
            currency=currency,
            price_applies_to=price_applies_to,
            applicable_license_ids=applicable_license_ids,
            applicable_license_price_ids=applicable_license_price_ids,
            applicable_addon_ids=applicable_addon_ids,
            applicable_addon_price_ids=applicable_addon_price_ids,
            grants=grants,
            flag_grants=flag_grants,
            redemption_rules=redemption_rules,
        )
        return await self._api.send("POST", "/vouchers", Voucher, body=body)

    async def update(
        self,
        voucher_id: str,
        *,
        name: str,
        voucher_type: VoucherType,
        duration: VoucherDuration,
        code: str | None = None,
        description: str | None = None,
        duration_in_periods: int | None = None,
        starts_at: datetime | str | None = None,
        expires_at: datetime | str | None = None,
        max_redemptions: int | None = None,
        restricted_customer_slug: str | None = None,
        price_discount_type: DiscountType | None = None,
        price_discount_value: str | None = None,
        currency: str | None = None,
        price_applies_to: DiscountAppliesTo | None = None,
        applicable_license_ids: Sequence[str] | None = None,
        applicable_license_price_ids: Sequence[str] | None = None,
        applicable_addon_ids: Sequence[str] | None = None,
        applicable_addon_price_ids: Sequence[str] | None = None,
        grants: Sequence[VoucherGrantParam] | None = None,
        flag_grants: Mapping[str, str] | None = None,
        redemption_rules: RedemptionRulesParam | None = None,
    ) -> Voucher:
        """Replace a voucher, and return it. The arguments are :meth:`create`'s.

        A ``DRAFT`` is replaced whole, but its type. An ``ACTIVE`` voucher takes a new name,
        description, expiry and redemption count only; its other members must stay as they are
        (``UpdateVoucher.NotEditable``).
        """
        body = _voucher(
            name=name,
            voucher_type=voucher_type,
            duration=duration,
            code=code,
            description=description,
            duration_in_periods=duration_in_periods,
            starts_at=starts_at,
            expires_at=expires_at,
            max_redemptions=max_redemptions,
            restricted_customer_slug=restricted_customer_slug,
            price_discount_type=price_discount_type,
            price_discount_value=price_discount_value,
            currency=currency,
            price_applies_to=price_applies_to,
            applicable_license_ids=applicable_license_ids,
            applicable_license_price_ids=applicable_license_price_ids,
            applicable_addon_ids=applicable_addon_ids,
            applicable_addon_price_ids=applicable_addon_price_ids,
            grants=grants,
            flag_grants=flag_grants,
            redemption_rules=redemption_rules,
        )
        return await self._api.send("PUT", api_path("vouchers", voucher_id), Voucher, body=body)

    async def delete(self, voucher_id: str) -> None:
        """Delete a voucher no instance ever redeemed, whatever its status, freeing its code.

        Raises:
            ConflictError: It was redeemed at least once, or a checkout waiting for its payment
                applies it (``DeleteVoucher.Redeemed``): :meth:`archive` it instead.
        """
        await self._api.send_empty("DELETE", api_path("vouchers", voucher_id))

    async def publish(self, voucher_id: str) -> Voucher:
        """Make a ``DRAFT`` voucher redeemable."""
        return await self._api.send("POST", api_path("vouchers", voucher_id, "publish"), Voucher)

    async def archive(self, voucher_id: str) -> Voucher:
        """Stop a voucher being redeemed. Redemptions already made keep applying until revoked."""
        return await self._api.send("POST", api_path("vouchers", voucher_id, "archive"), Voucher)

    async def list_redemptions(
        self, voucher_id: str, *, limit: int | None = None
    ) -> builtins.list[Redemption]:
        """Return every redemption of a voucher, newest first.

        Args:
            voucher_id: The voucher.
            limit: The most redemptions to return. Every page is walked when omitted.
        """
        return await self._api.list_all(
            api_path("vouchers", voucher_id, "redemptions"), Redemption, limit=check_limit(limit)
        )

    async def lookup(self, code: str) -> Voucher:
        """Return the voucher a code names, matched without case or separators.

        The code travels in the request body, never in a URL.
        """
        return await self._api.send(
            "POST", "/vouchers/lookup", Voucher, body={"code": code}, idempotent=True
        )

    async def validate(
        self,
        code: str,
        *,
        instance_slug: str | None = None,
        license_price_id: str | None = None,
    ) -> Validity:
        """Run the redemption checks of a code without redeeming it.

        ``valid`` says whether it would apply; otherwise ``reason`` is the first check that
        failed, and ``rule`` the eligibility rule.

        Args:
            code: The code.
            instance_slug: Also run the checks that need the redeeming instance.
            license_price_id: The ``FLAT_FEE`` price a subscription would start on, read instead
                of the instance's live subscription.
        """
        body = {
            "code": code,
            **compact({"instanceSlug": instance_slug, "licensePriceId": license_price_id}),
        }
        return await self._api.send(
            "POST", "/vouchers/validate", Validity, body=body, idempotent=True
        )


def _voucher(
    *,
    name: str,
    voucher_type: VoucherType,
    duration: VoucherDuration,
    code: str | None,
    description: str | None,
    duration_in_periods: int | None,
    starts_at: datetime | str | None,
    expires_at: datetime | str | None,
    max_redemptions: int | None,
    restricted_customer_slug: str | None,
    price_discount_type: DiscountType | None,
    price_discount_value: str | None,
    currency: str | None,
    price_applies_to: DiscountAppliesTo | None,
    applicable_license_ids: Sequence[str] | None,
    applicable_license_price_ids: Sequence[str] | None,
    applicable_addon_ids: Sequence[str] | None,
    applicable_addon_price_ids: Sequence[str] | None,
    grants: Sequence[VoucherGrantParam] | None,
    flag_grants: Mapping[str, str] | None,
    redemption_rules: RedemptionRulesParam | None,
) -> dict[str, Any]:
    return {
        "name": name,
        "voucherType": voucher_type,
        "duration": duration,
        **compact(
            {
                "code": code,
                "description": description,
                "durationInPeriods": duration_in_periods,
                "startsAt": optional_datetime(starts_at),
                "expiresAt": optional_datetime(expires_at),
                "maxRedemptions": max_redemptions,
                "restrictedCustomerSlug": restricted_customer_slug,
                "priceDiscountType": price_discount_type,
                "priceDiscountValue": price_discount_value,
                "currency": currency,
                "priceAppliesTo": price_applies_to,
                "applicableLicenseIds": _listed(applicable_license_ids),
                "applicableLicensePriceIds": _listed(applicable_license_price_ids),
                "applicableAddonIds": _listed(applicable_addon_ids),
                "applicableAddonPriceIds": _listed(applicable_addon_price_ids),
                "grants": _listed(grants),
                "flagGrants": (
                    [
                        {"flagSlug": flag, "variant": variant}
                        for flag, variant in flag_grants.items()
                    ]
                    if flag_grants is not None
                    else None
                ),
                "redemptionRules": dict(redemption_rules) if redemption_rules is not None else None,
            }
        ),
    }


def _listed(values: Sequence[Any] | None) -> list[Any] | None:
    return list(values) if values is not None else None
