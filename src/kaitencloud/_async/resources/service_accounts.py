# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import datetime

from ..._utils import api_path, compact, optional_datetime
from ...types import PlainToken, Scope, ServiceAccount, Token
from ._base import AsyncResource

__all__ = ["AsyncServiceAccounts"]


class AsyncServiceAccounts(AsyncResource):
    """Service accounts: machine identities in your organization, and their API tokens."""

    async def list(self) -> builtins.list[ServiceAccount]:
        """Return every service account, walking all pages."""
        return await self._api.list_all("/service-accounts", ServiceAccount)

    async def get(self, service_account_slug: str) -> ServiceAccount:
        """Return the service account identified by ``service_account_slug``."""
        return await self._api.get(
            api_path("service-accounts", service_account_slug), ServiceAccount
        )

    async def create(self, *, name: str, slug: str | None = None) -> ServiceAccount:
        """Create a service account.

        Args:
            name: The account's name, e.g. ``"billing-sync"``.
            slug: Its URL-friendly identifier, generated when omitted. Immutable once set.
        """
        body = compact({"name": name, "slug": slug})
        return await self._api.send("POST", "/service-accounts", ServiceAccount, body=body)

    async def update(self, service_account_slug: str, *, name: str) -> None:
        """Rename a service account. Its slug cannot be changed."""
        await self._api.send_empty(
            "PUT", api_path("service-accounts", service_account_slug), body={"name": name}
        )

    async def list_tokens(self, service_account_slug: str) -> builtins.list[Token]:
        """Return the service account's tokens, walking all pages. Never their secrets."""
        return await self._api.list_all(
            api_path("service-accounts", service_account_slug, "tokens"), Token
        )

    async def create_token(
        self,
        service_account_slug: str,
        *,
        name: str,
        scopes: Sequence[Scope] | None = None,
        slug: str | None = None,
        expires_at: datetime | str | None = None,
    ) -> PlainToken:
        """Create a token for the service account, and return it with its secret.

        The secret, :attr:`~kaitencloud.types.PlainToken.token`, is in this response and
        nowhere else: the API keeps only a hash of it. Store it now -- a lost secret can be
        replaced, never recovered.

        Args:
            service_account_slug: The service account the token authenticates as.
            name: A label, unique among the account's active tokens.
            scopes: What the token may do, e.g. ``["read:customers", "write:instances"]``;
                :data:`~kaitencloud.types.Scope` lists every one the API knows. ``None``
                inherits the service account's scopes. ``write:X`` implies ``read:X``.
            slug: Its URL-friendly identifier, generated when omitted. It is what
                :meth:`delete_token` takes.
            expires_at: When the token stops working. Omitted, it lasts until revoked.
        """
        body = {
            "name": name,
            "scopes": list(scopes) if scopes is not None else None,
            **compact({"slug": slug, "expiresAt": optional_datetime(expires_at)}),
        }
        return await self._api.send(
            "POST",
            api_path("service-accounts", service_account_slug, "tokens"),
            PlainToken,
            body=body,
        )

    async def delete_token(self, service_account_slug: str, token_slug: str) -> None:
        """Revoke the token identified by ``token_slug``. The revocation is immediate."""
        await self._api.send_empty(
            "DELETE", api_path("service-accounts", service_account_slug, "tokens", token_slug)
        )
