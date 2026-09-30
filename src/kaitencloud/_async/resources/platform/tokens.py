# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from collections.abc import Sequence
from datetime import timedelta

from ...._utils import api_path, compact, format_duration, validate_uuid
from ....types import PlainToken, Scope, Token
from .._base import AsyncResource

__all__ = ["AsyncPlatformTokens"]


class AsyncPlatformTokens(AsyncResource):
    """Organization tokens (``ksh_...``) minted by this platform credential.

    A platform credential proves who is calling, never where. To act inside an organization
    it does not become organization-scoped: it mints an ordinary organization token, bounded
    by its own scopes, and the work is done with that.
    """

    async def mint(
        self,
        organization_id: str,
        *,
        name: str,
        scopes: Sequence[Scope] | None = None,
        ttl: timedelta | str | None = None,
    ) -> PlainToken:
        """Mint an organization token, and return it with its secret.

        The secret, :attr:`~kaitencloud.types.PlainToken.token`, is in this response only. Two
        things are easy to get wrong:

        - **Revocation cascades.** Revoking this platform credential revokes every token it
          minted. Rotate by minting the new token, adopting it, then revoking the old one --
          never the other way round.
        - **The slug is the handle.** :meth:`revoke` takes the token's
          :attr:`~kaitencloud.types.PlainToken.slug`, which the server generates. The name you
          chose will not do; :meth:`list` maps one to the other.

        Args:
            organization_id: The organization to mint the token in.
            name: A label, unique among the organization's active tokens.
            scopes: The token's scopes, each of which this platform credential must hold;
                :data:`~kaitencloud.types.Scope` lists every one an organization token can carry.
                ``None`` inherits all of them, which is rarely what a machine consumer needs.
            ttl: How long the token lives, as a :class:`~datetime.timedelta` or a Go duration
                such as ``"24h"``. Omitted, it lasts until revoked.

        Raises:
            PermissionDeniedError: A requested scope is not held by this platform credential.
            ConflictError: An active token of the organization already has this name.
        """
        body = compact(
            {
                "name": name,
                "scopes": list(scopes) if scopes is not None else None,
                "ttl": format_duration(ttl) if ttl is not None else None,
            }
        )
        return await self._api.send("POST", _tokens(organization_id), PlainToken, body=body)

    async def list(self, organization_id: str) -> builtins.list[Token]:
        """Return the active tokens this platform credential minted in an organization.

        It is the way back from the name you chose to the slug :meth:`revoke` takes. Only this
        credential's own tokens are listed, and never their secrets.
        """
        return await self._api.get_list(_tokens(organization_id), Token)

    async def revoke(self, organization_id: str, token_slug: str) -> None:
        """Revoke a token this platform credential minted. Immediate and final."""
        await self._api.send_empty(
            "DELETE",
            api_path(
                "platform",
                "organizations",
                validate_uuid(organization_id, "organization_id"),
                "tokens",
                token_slug,
            ),
        )


def _tokens(organization_id: str) -> str:
    return api_path(
        "platform", "organizations", validate_uuid(organization_id, "organization_id"), "tokens"
    )
