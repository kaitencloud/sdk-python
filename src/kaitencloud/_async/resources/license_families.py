# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from typing import Any

from ..._utils import api_path
from ...types import LicenseFamilyView
from ._base import AsyncResource

__all__ = ["AsyncLicenseFamilies"]


class AsyncLicenseFamilies(AsyncResource):
    """License families: the products whose versions :attr:`KaitenClient.licenses` are.

    A family's slug survives renames and new versions, so it is the identifier worth storing:
    a version's slug names the row a customer bought, and a new one appears every time a
    version is published. Reading a family resolves it to the version it currently serves.
    """

    async def list(self) -> builtins.list[LicenseFamilyView]:
        """Return every license family, each with the version it currently serves.

        A family with nothing published -- every version a draft, or all of them archived --
        is listed too, with ``current_version`` set to ``None``.
        """
        return await self._api.list_all("/license-families", LicenseFamilyView)

    async def get(
        self, family_slug: str, *, version: int | None = None, include_versions: bool = False
    ) -> LicenseFamilyView:
        """Resolve the family identified by ``family_slug`` to one of its versions.

        With no options it returns, as ``current_version``, the version the family serves
        today: its default version, or failing that its highest-numbered published one. That
        is the point of addressing a family -- publishing a new version changes what this
        returns, with no change to the caller.

        Args:
            family_slug: The family's slug.
            version: Read this version number instead, whatever its lifecycle state, archived
                included: pinned access stays pinned.
            include_versions: Also return every version of the family, oldest first, as
                ``versions``. It makes a family with no published version readable too.

        Raises:
            NotFoundError: No family has this slug -- or it exists but has no published
                version and ``include_versions`` was not asked, which the problem's ``code``
                tells apart: ``GetLicenseFamily.NoPublishedVersion``.
        """
        params: dict[str, Any] = {}
        if version is not None:
            params["version"] = version
        if include_versions:
            params["include"] = "versions"
        return await self._api.get(
            api_path("license-families", family_slug), LicenseFamilyView, params=params or None
        )
