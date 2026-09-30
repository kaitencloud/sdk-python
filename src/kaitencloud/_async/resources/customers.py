# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from collections.abc import Mapping
from typing import Any

from ..._utils import api_path, compact, integration_body, integrations_body
from ...types import Customer, CustomerIntegration, IntegrationParam
from ._base import AsyncResource

__all__ = ["AsyncCustomers"]


class AsyncCustomers(AsyncResource):
    """Customers: the end clients of your product, each owning its instances."""

    async def list(self) -> builtins.list[Customer]:
        """Return every customer, walking all pages."""
        return await self._api.list_all("/customers", Customer)

    async def get(self, customer_slug: str) -> Customer:
        """Return the customer identified by ``customer_slug``."""
        return await self._api.get(api_path("customers", customer_slug), Customer)

    async def create(
        self,
        *,
        name: str,
        slug: str | None = None,
        external_customer_id: str | None = None,
        domain: str | None = None,
        integrations: Mapping[str, IntegrationParam] | None = None,
    ) -> Customer:
        """Create a customer.

        Args:
            name: The customer's name.
            slug: Its URL-friendly identifier, unique in the organization. Generated from the
                name when omitted, and immutable once set.
            external_customer_id: Its identifier in your own systems, e.g. your CRM.
            domain: Its domain name, e.g. ``"acme.com"``.
            integrations: Links to records in third-party systems, keyed by adapter name.
                Only settable here: afterwards, use :meth:`update_integration`.

        Raises:
            ConflictError: The slug is taken, or the organization reached its customer limit.
        """
        body = compact(
            {
                "name": name,
                "slug": slug,
                "externalCustomerId": external_customer_id,
                "domain": domain,
                "integrations": integrations_body(integrations),
            }
        )
        return await self._api.send("POST", "/customers", Customer, body=body)

    async def update(
        self,
        customer_slug: str,
        *,
        name: str,
        external_customer_id: str | None = None,
        domain: str | None = None,
    ) -> None:
        """Replace a customer's details.

        A full replacement: the external customer id and the domain are cleared when left out.
        The slug cannot be changed, and integrations have their own methods.
        """
        body = compact({"name": name, "externalCustomerId": external_customer_id, "domain": domain})
        await self._api.send_empty("PUT", api_path("customers", customer_slug), body=body)

    async def delete(self, customer_slug: str) -> None:
        """Delete the customer identified by ``customer_slug``."""
        await self._api.send_empty("DELETE", api_path("customers", customer_slug))

    async def get_integration(
        self, customer_slug: str, integration_name: str
    ) -> CustomerIntegration:
        """Return the customer's link to the ``integration_name`` adapter."""
        return await self._api.get(
            api_path("customers", customer_slug, "integrations", integration_name),
            CustomerIntegration,
        )

    async def create_integration(
        self,
        customer_slug: str,
        integration_name: str,
        *,
        external_id: str,
        metadata: Mapping[str, Any] | None = None,
        web_url: str | None = None,
        last_error: str | None = None,
    ) -> CustomerIntegration:
        """Link the customer to a record in the ``integration_name`` adapter.

        Args:
            customer_slug: The customer to link.
            integration_name: The adapter, e.g. ``"attio"``.
            external_id: The record's identifier in the third-party system.
            metadata: Adapter-specific metadata.
            web_url: An absolute http(s) link to the record.
            last_error: The last synchronization error, if any.
        """
        return await self._api.send(
            "POST",
            api_path("customers", customer_slug, "integrations", integration_name),
            CustomerIntegration,
            body=integration_body(
                external_id=external_id, metadata=metadata, web_url=web_url, last_error=last_error
            ),
        )

    async def update_integration(
        self,
        customer_slug: str,
        integration_name: str,
        *,
        external_id: str,
        metadata: Mapping[str, Any] | None = None,
        web_url: str | None = None,
        last_error: str | None = None,
    ) -> CustomerIntegration:
        """Replace the customer's link to the ``integration_name`` adapter, and return it."""
        return await self._api.send(
            "PUT",
            api_path("customers", customer_slug, "integrations", integration_name),
            CustomerIntegration,
            body=integration_body(
                external_id=external_id, metadata=metadata, web_url=web_url, last_error=last_error
            ),
        )

    async def delete_integration(self, customer_slug: str, integration_name: str) -> None:
        """Remove the customer's link to the ``integration_name`` adapter."""
        await self._api.send_empty(
            "DELETE", api_path("customers", customer_slug, "integrations", integration_name)
        )
