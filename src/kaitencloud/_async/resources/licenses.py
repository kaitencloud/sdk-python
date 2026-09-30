# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from typing import Literal

from ..._types import EntitlementValueInput
from ..._utils import api_path, compact, entitlement_value
from ...types import License, LicenseEntitlement, LicenseType
from ._base import AsyncResource

__all__ = ["AsyncLicenses"]


class AsyncLicenses(AsyncResource):
    """Licenses: the versions of a license family, each granting values of catalog entitlements.

    A license is one version of a product, the *license family*. Creating a license without
    naming a family opens a new one, of which it is version 1; naming a family with
    ``family_slug`` or ``family_id`` adds that family's next version. Each version moves
    through a lifecycle -- ``DRAFT``, ``PUBLISHED``, ``ARCHIVED`` -- by :meth:`publish`,
    :meth:`archive` and :meth:`unarchive`, and :attr:`KaitenClient.license_families` resolves
    a family to the version it currently serves.
    """

    async def list(self) -> builtins.list[License]:
        """Return every license, walking all pages."""
        return await self._api.list_all("/licenses", License)

    async def get(self, license_slug: str) -> License:
        """Return the license identified by ``license_slug``."""
        return await self._api.get(api_path("licenses", license_slug), License)

    async def create(
        self,
        *,
        name: str,
        type: LicenseType,
        description: str = "",
        is_default: bool = False,
        version_name: str | None = None,
        slug: str | None = None,
        family_slug: str | None = None,
        family_id: str | None = None,
        lifecycle_state: Literal["DRAFT", "PUBLISHED"] | None = None,
    ) -> License:
        """Create a license: a new license family, or the next version of an existing one.

        Without ``family_slug`` or ``family_id`` this opens a new family, of which the license
        is version 1, and the family takes the license's slug. With either, it adds the next
        version to that family -- the version number is always assigned by the server, never
        reused within a family, and cannot be sent. Two families may share a name: the family,
        not the name, is the product. Where the deployment limits how many licenses an
        organization may have, only a new family counts against that limit.

        Args:
            name: The license's name, e.g. ``"Growth"``.
            type: ``DEVELOPMENT``, ``TRIAL``, ``PAID`` or ``COMMUNITY``.
            description: A description, up to 500 characters.
            is_default: Whether this version is the one its family puts forward. Only a
                ``PUBLISHED`` version can be.
            version_name: A label for this version, e.g. ``"Winter 2026"``. Defaults to
                ``"Version - <version>"``.
            slug: Its URL-friendly identifier. When omitted, a new version of an existing
                family takes ``<family-slug>-v<version>``, and a new family's first version one
                generated from its name. Immutable once set.
            family_slug: The family this license is a new version of, by slug.
            family_id: The same family by identifier. Sent together, the two must agree.
            lifecycle_state: ``DRAFT`` to create the version off sale, to be put on sale with
                :meth:`publish`. ``PUBLISHED`` when omitted. A version is never created
                ``ARCHIVED``: it is archived with :meth:`archive` once it has been on sale.

        Raises:
            NotFoundError: ``family_slug`` or ``family_id`` names no family
                (``CreateLicense.FamilyNotFound``).
            ConflictError: ``is_default=True`` on a draft (``CreateLicense.DefaultMustBePublished``),
                or the organization reached its license limit, which only a new family counts
                against.
            UnprocessableEntityError: ``family_slug`` and ``family_id`` name different families
                (``CreateLicense.FamilyMismatch``).
        """
        body = {
            "name": name,
            "description": description,
            "type": type,
            "isDefault": is_default,
            **compact(
                {
                    "versionName": version_name,
                    "slug": slug,
                    "familySlug": family_slug,
                    "familyId": family_id,
                    "lifecycleState": lifecycle_state,
                }
            ),
        }
        return await self._api.send("POST", "/licenses", License, body=body)

    async def update(
        self,
        license_slug: str,
        *,
        name: str,
        type: LicenseType,
        description: str = "",
        is_default: bool = False,
        version_name: str | None = None,
    ) -> None:
        """Replace a license version's details.

        A full replacement. The slug, the version number, the family and the lifecycle state
        are not part of it: the first three never change, and the state moves only through
        :meth:`publish`, :meth:`archive` and :meth:`unarchive`. ``is_default=True`` takes the
        flag from the family's previous default, and ``False`` unsets it on this version.

        Raises:
            ConflictError: ``is_default=True`` on a version that is not ``PUBLISHED``
                (``UpdateLicense.DefaultMustBePublished``): publish or unarchive it first.
        """
        body = {
            "name": name,
            "description": description,
            "type": type,
            "isDefault": is_default,
            **compact({"versionName": version_name}),
        }
        await self._api.send_empty("PUT", api_path("licenses", license_slug), body=body)

    async def publish(self, license_slug: str) -> License:
        """Put a ``DRAFT`` version on sale, and return it ``PUBLISHED``.

        It can then be made its family's default, and a family without a default serves its
        highest-numbered published version, which may be this one.

        Raises:
            ConflictError: The version is not a draft (``PublishLicense.NotADraft``). An
                archived version goes back on sale with :meth:`unarchive`.
        """
        return await self._api.send("POST", api_path("licenses", license_slug, "publish"), License)

    async def archive(self, license_slug: str) -> License:
        """Withdraw a ``PUBLISHED`` version from sale, and return it ``ARCHIVED``.

        Its family stops resolving to it and no instance can be assigned to it any more, while
        the instances already on it keep it.

        Raises:
            ConflictError: The version is not published (``ArchiveLicense.NotPublished``) -- a
                draft that was never on sale is deleted instead -- or it is its family's
                default (``ArchiveLicense.DefaultMustBePublished``): make another version the
                default, or unset it, first.
        """
        return await self._api.send("POST", api_path("licenses", license_slug, "archive"), License)

    async def unarchive(self, license_slug: str) -> License:
        """Put an ``ARCHIVED`` version back on sale, and return it ``PUBLISHED``.

        Raises:
            ConflictError: The version is not archived (``UnarchiveLicense.NotArchived``). A
                draft goes on sale with :meth:`publish`.
        """
        return await self._api.send(
            "POST", api_path("licenses", license_slug, "unarchive"), License
        )

    async def delete(self, license_slug: str) -> None:
        """Delete the license version identified by ``license_slug``.

        Deleting a family's last version deletes the family too, and frees its slug. A deleted
        version's number is never reused by the family's next version.
        """
        await self._api.send_empty("DELETE", api_path("licenses", license_slug))

    async def list_entitlements(self, license_slug: str) -> builtins.list[LicenseEntitlement]:
        """Return every entitlement the license grants, with its value, walking all pages."""
        return await self._api.list_all(
            api_path("licenses", license_slug, "entitlements"), LicenseEntitlement
        )

    async def get_entitlement(self, license_slug: str, entitlement_slug: str) -> LicenseEntitlement:
        """Return the value the license grants the entitlement identified by ``entitlement_slug``."""
        return await self._api.get(
            api_path("licenses", license_slug, "entitlements", entitlement_slug),
            LicenseEntitlement,
        )

    async def associate_entitlement(
        self,
        license_slug: str,
        entitlement_slug: str,
        value: EntitlementValueInput,
        *,
        overage_percent: int | None = None,
    ) -> None:
        """Grant an entitlement under the license.

        Args:
            license_slug: The license that grants.
            entitlement_slug: The entitlement granted.
            value: What is granted: ``True`` or ``False`` for a BOOLEAN entitlement, a number
                for a NUMBER one -- :data:`kaitencloud.UNLIMITED` for no cap -- and a mapping
                for a CONFIG one.
            overage_percent: How far usage may exceed a numeric value before reports are
                refused: ``0`` makes a hard limit, ``10`` tolerates 10% over. It is ``-1``
                exactly when the value is unlimited. The server picks it when omitted. Sent as
                ``limitCapExceededOveragePercent``.

        Raises:
            ConflictError: The license already grants this entitlement.
        """
        body = {
            "entitlementSlug": entitlement_slug,
            "value": entitlement_value(value),
            **compact({"limitCapExceededOveragePercent": overage_percent}),
        }
        await self._api.send_empty(
            "POST", api_path("licenses", license_slug, "entitlements"), body=body
        )

    async def update_entitlement(
        self,
        license_slug: str,
        entitlement_slug: str,
        value: EntitlementValueInput,
        *,
        overage_percent: int | None = None,
    ) -> None:
        """Change what the license grants an entitlement.

        A full replacement of the grant: see :meth:`associate_entitlement` for ``value`` and
        ``overage_percent``.
        """
        body = {
            "value": entitlement_value(value),
            **compact({"limitCapExceededOveragePercent": overage_percent}),
        }
        await self._api.send_empty(
            "PUT", api_path("licenses", license_slug, "entitlements", entitlement_slug), body=body
        )

    async def delete_entitlement(self, license_slug: str, entitlement_slug: str) -> None:
        """Stop granting the entitlement identified by ``entitlement_slug`` under the license."""
        await self._api.send_empty(
            "DELETE", api_path("licenses", license_slug, "entitlements", entitlement_slug)
        )
