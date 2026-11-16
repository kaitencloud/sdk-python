# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from ...._utils import compact
from ....types import (
    BillingCapabilities,
    BillingHealth,
    BillingSettings,
    ClosePeriodsReport,
    CollectionMethod,
    SyncReport,
)
from ..._http import AsyncAPIClient
from .._base import AsyncResource
from .addons import AsyncBillingAddons
from .customers import AsyncBillingCustomers
from .invoices import AsyncBillingHandoff, AsyncBillingInvoices
from .license_prices import AsyncBillingLicensePrices
from .public import AsyncBillingPublic, AsyncBillingSession
from .sessions import (
    AsyncBillingCheckoutSessions,
    AsyncBillingCustomerSessions,
    AsyncBillingPublishableKeys,
)
from .subscriptions import (
    AsyncBillingInstanceAddons,
    AsyncBillingInstanceVouchers,
    AsyncBillingSubscriptions,
)
from .vouchers import AsyncBillingVouchers

__all__ = [
    "AsyncBilling",
    "AsyncBillingAddons",
    "AsyncBillingCheckoutSessions",
    "AsyncBillingCustomerSessions",
    "AsyncBillingCustomers",
    "AsyncBillingHandoff",
    "AsyncBillingInstanceAddons",
    "AsyncBillingInstanceVouchers",
    "AsyncBillingInvoices",
    "AsyncBillingLicensePrices",
    "AsyncBillingPublic",
    "AsyncBillingPublishableKeys",
    "AsyncBillingSession",
    "AsyncBillingSubscriptions",
    "AsyncBillingVouchers",
]


class AsyncBilling(AsyncResource):
    """Billing: the organization's settings and payment providers, and a namespace per resource.

    Kaiten composes every invoice from the prices of a license version, its add-ons and the
    usage it metered. Each subscription names who issues and collects them: ``NOOP``, the
    organization itself through :attr:`handoff`, or a payment provider. Most operations here
    require billing to be enabled for the organization; :meth:`get_capabilities` says whether
    it is.
    """

    __slots__ = (
        "addons",
        "checkout_sessions",
        "customer_sessions",
        "customers",
        "handoff",
        "instance_addons",
        "instance_vouchers",
        "invoices",
        "license_prices",
        "public",
        "publishable_keys",
        "session",
        "subscriptions",
        "vouchers",
    )

    addons: AsyncBillingAddons
    """The add-on catalog: families, versions, grants, prices and the license families they fit."""

    checkout_sessions: AsyncBillingCheckoutSessions
    """Anonymous checkouts, as the organization reads them."""

    customer_sessions: AsyncBillingCustomerSessions
    """Customer sessions (``kst_...``), for a customer's browser to act on its own billing."""

    customers: AsyncBillingCustomers
    """A customer's billing: its payment method, and the payment provider's portal."""

    handoff: AsyncBillingHandoff
    """The accounting handoff: invoices claimed in leased batches and acknowledged one by one."""

    instance_addons: AsyncBillingInstanceAddons
    """The add-ons an instance holds."""

    instance_vouchers: AsyncBillingInstanceVouchers
    """The vouchers an instance redeemed."""

    invoices: AsyncBillingInvoices
    """The organization's invoices."""

    license_prices: AsyncBillingLicensePrices
    """The prices of license versions, and the invoice a subscription to one would get."""

    public: AsyncBillingPublic
    """What a publishable key (``pk_...``) reaches. Build the client with that key."""

    publishable_keys: AsyncBillingPublishableKeys
    """Publishable keys (``pk_...``), which a web page reads the public catalog with."""

    session: AsyncBillingSession
    """What a customer session (``kst_...``) reaches. Build the client with that session."""

    subscriptions: AsyncBillingSubscriptions
    """Instances' subscriptions."""

    vouchers: AsyncBillingVouchers
    """The organization's vouchers."""

    def __init__(self, api: AsyncAPIClient) -> None:
        super().__init__(api)
        self.addons = AsyncBillingAddons(api)
        self.checkout_sessions = AsyncBillingCheckoutSessions(api)
        self.customer_sessions = AsyncBillingCustomerSessions(api)
        self.customers = AsyncBillingCustomers(api)
        self.handoff = AsyncBillingHandoff(api)
        self.instance_addons = AsyncBillingInstanceAddons(api)
        self.instance_vouchers = AsyncBillingInstanceVouchers(api)
        self.invoices = AsyncBillingInvoices(api)
        self.license_prices = AsyncBillingLicensePrices(api)
        self.public = AsyncBillingPublic(api)
        self.publishable_keys = AsyncBillingPublishableKeys(api)
        self.session = AsyncBillingSession(api)
        self.subscriptions = AsyncBillingSubscriptions(api)
        self.vouchers = AsyncBillingVouchers(api)

    async def get_settings(self) -> BillingSettings:
        """Return the organization's billing defaults.

        They are the collection method and payment terms a subscription gets when it names none
        of its own. An organization that never wrote them has ``SEND_INVOICE`` and 30 days.
        """
        return await self._api.get("/billing/settings", BillingSettings)

    async def update_settings(
        self,
        *,
        default_collection_method: CollectionMethod,
        default_days_until_due: int,
        handoff_stripe_invoices: bool,
    ) -> BillingSettings:
        """Replace the organization's billing defaults, and return them.

        A subscription that names its own terms keeps them; the others take these at their
        next invoice.

        Args:
            default_collection_method: ``SEND_INVOICE`` sends an invoice for payment;
                ``CHARGE_AUTOMATICALLY`` charges the customer's payment method, on a provider
                that can.
            default_days_until_due: Days an invoice is due after it is issued, 0 to 365.
            handoff_stripe_invoices: Whether invoices a payment provider issues also enter the
                handoff queue, for an accounting system that wants every invoice.
        """
        body = {
            "defaultCollectionMethod": default_collection_method,
            "defaultDaysUntilDue": default_days_until_due,
            "handoffStripeInvoices": handoff_stripe_invoices,
        }
        return await self._api.send("PUT", "/billing/settings", BillingSettings, body=body)

    async def get_capabilities(self) -> BillingCapabilities:
        """Return whether billing is enabled -- and if not, why -- and what it can do here.

        Who can collect the organization's invoices, and which parts of billing this release
        ships, so a client shows only what works. It answers even when billing is disabled.
        """
        return await self._api.get("/billing/capabilities", BillingCapabilities)

    async def get_health(self) -> BillingHealth:
        """Return what the organization's billing needs attention for, computed when read.

        Periods waiting for their close, held invoices, invoices a payment provider keeps
        refusing, reconciliation mismatches, each provider's sync, overdue invoices and the
        handoff backlog.
        """
        return await self._api.get("/billing/health", BillingHealth)

    async def sync(self) -> SyncReport:
        """Run one sync pass now with each payment provider the organization connected.

        What was paid, voided or finalized in a provider is mirrored, as the periodic pass does.

        Raises:
            ConflictError: No provider is connected (``SyncProvider.NotConnected``).
        """
        return await self._api.send("POST", "/billing/sync", SyncReport)

    async def close_periods(self, *, instance_slug: str | None = None) -> ClosePeriodsReport:
        """Close the subscriptions whose period has ended, now rather than at the next pass.

        Each one's ``RENEWAL`` invoice is composed and issued -- or held, when its usage journal
        fails a check -- and its period advances. Only what is due closes, at most a batch per
        call: ``has_more`` says when more is left.

        Args:
            instance_slug: Close only this instance's subscription.
        """
        return await self._api.send(
            "POST",
            "/billing/close-periods",
            ClosePeriodsReport,
            body=compact({"instanceSlug": instance_slug}),
        )
