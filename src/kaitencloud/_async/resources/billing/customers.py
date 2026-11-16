# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from ...._utils import api_path, compact
from ....types import (
    CompletedPaymentMethodSession,
    CustomerBilling,
    PaymentMethodSession,
    PortalSession,
)
from .._base import AsyncResource

__all__ = ["AsyncBillingCustomers"]


class AsyncBillingCustomers(AsyncResource):
    """A customer's billing: its payment method, and its payment provider's portal.

    The pages it opens are the provider's own: Kaiten never sees card data.
    """

    async def get(self, customer_slug: str) -> CustomerBilling:
        """Return the customer's billing e-mail, and its side in each payment provider.

        Its id there and the labels of its default payment method -- never card data.
        """
        return await self._api.get(api_path("customers", customer_slug, "billing"), CustomerBilling)

    async def detach_payment_method(self, customer_slug: str) -> None:
        """Remove the customer's payment method from its payment provider.

        Raises:
            ConflictError: A live subscription of the customer is charged automatically
                (``.InUseByAutomaticCollection``), or there is no payment method.
        """
        await self._api.send_empty(
            "DELETE", api_path("customers", customer_slug, "billing", "payment-method")
        )

    async def create_payment_method_session(
        self, customer_slug: str, *, return_url: str, currency: str | None = None
    ) -> PaymentMethodSession:
        """Open the payment provider's page where the customer saves a payment method.

        Send the customer to its ``url``. When it comes back to ``return_url``, with
        ``kaiten_setup_session`` in the query, call :meth:`complete_payment_method_session`.

        Args:
            customer_slug: The customer.
            return_url: Where the customer comes back to: https, or http on localhost.
            currency: The currency the payment method is set up in; required when the customer
                has no live subscription, whose currency is used otherwise.
        """
        return await self._api.send(
            "POST",
            api_path("customers", customer_slug, "billing", "payment-method-session"),
            PaymentMethodSession,
            body={"returnUrl": return_url, **compact({"currency": currency})},
        )

    async def complete_payment_method_session(
        self, customer_slug: str, session_id: str
    ) -> CompletedPaymentMethodSession:
        """Check a setup session with the provider, and charge the customer's invoices to it.

        The redirect is never trusted: the provider is asked. Idempotent.

        Raises:
            NotFoundError: The session is unknown, or another customer's.
            ConflictError: The customer did not complete it (``.SessionNotComplete``).
        """
        return await self._api.send(
            "POST",
            api_path(
                "customers",
                customer_slug,
                "billing",
                "payment-method-session",
                session_id,
                "complete",
            ),
            CompletedPaymentMethodSession,
            idempotent=True,
        )

    async def create_portal_session(self, customer_slug: str, *, return_url: str) -> PortalSession:
        """Open the payment provider's portal, where the customer manages its payment methods.

        What it changes there reaches Kaiten through the provider sync.

        Args:
            customer_slug: The customer.
            return_url: Where the portal sends the customer back: https, or http on localhost.
        """
        return await self._api.send(
            "POST",
            api_path("customers", customer_slug, "billing", "portal-session"),
            PortalSession,
            body={"returnUrl": return_url},
        )
