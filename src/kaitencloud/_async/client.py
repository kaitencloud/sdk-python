# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The Kaiten API clients: one per API surface."""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from types import TracebackType

import httpx
from typing_extensions import Self

from .._constants import (
    DEFAULT_MAX_RETRIES,
    ENV_BASE_URL,
    ENV_PLATFORM_BASE_URL,
    ENV_PLATFORM_TOKEN,
    ENV_TOKEN,
)
from .._exceptions import CredentialError
from .._types import NOT_GIVEN, AsyncCredential, NotGiven, TimeoutTypes
from .._utils import normalize_base_url
from ..types import PlatformCredential
from ._http import AsyncAPIClient
from .resources import (
    AsyncComponents,
    AsyncConnectors,
    AsyncCustomers,
    AsyncDeploymentZones,
    AsyncEntitlementGroups,
    AsyncEntitlements,
    AsyncFeatureFlags,
    AsyncInstances,
    AsyncIntegrations,
    AsyncLicenseFamilies,
    AsyncLicenses,
    AsyncMetadataFields,
    AsyncReleases,
    AsyncServiceAccounts,
)
from .resources.platform import (
    AsyncPlatformConnectors,
    AsyncPlatformOrganizations,
    AsyncPlatformTokens,
    AsyncPlatformUsers,
)

__all__ = ["AsyncKaitenClient", "AsyncKaitenPlatformClient"]


class _AsyncBaseClient:
    _api: AsyncAPIClient

    @property
    def base_url(self) -> str:
        """The API prefix every request goes to, always ending in ``/api/``."""
        return self._api.base_url

    @property
    def max_retries(self) -> int:
        """How many times a failed request that is safe to repeat is retried."""
        return self._api.max_retries

    def with_options(
        self,
        *,
        timeout: TimeoutTypes | NotGiven = NOT_GIVEN,
        max_retries: int | NotGiven = NOT_GIVEN,
        default_headers: Mapping[str, str] | NotGiven = NOT_GIVEN,
    ) -> Self:
        """Return a copy of this client with some options changed.

        The copy shares this client's connection pool, so it is cheap to make per call::

            client.with_options(timeout=5, max_retries=0).customers.get("acme")

        Closing the copy leaves the pool open; closing the original closes it for both.
        """
        clone = copy.copy(self)
        clone._api = self._api.copy(
            timeout=timeout, max_retries=max_retries, default_headers=default_headers
        )
        clone._bind()
        return clone

    async def close(self) -> None:
        """Close the connection pool, unless it was passed in as ``http_client``."""
        await self._api.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    def _bind(self) -> None:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"


class AsyncKaitenClient(_AsyncBaseClient):
    """Client for the Kaiten Core API.

    The Core API is what an organization's own credential talks to: an organization token
    (``ksh_...``) or a JWT from your identity provider. It covers customers, instances,
    licenses, entitlements and usage, feature flags, releases and connectors::

        async with AsyncKaitenClient(token="ksh_...") as client:
            for customer in await client.customers.list():
                print(customer.slug)

    Args:
        token: The credential, or a callable returning it -- called before every request, so a
            rotated token is picked up. Defaults to the ``KAITEN_AUTH_TOKEN`` environment
            variable. A platform credential (``ksm_...``) is refused: use
            :class:`AsyncKaitenPlatformClient`.
        base_url: Where your Kaiten deployment's API lives, e.g. ``http://localhost:6000``.
            ``/api`` is appended when missing. Defaults to ``KAITEN_BASE_URL``; there is no
            default beyond it, since every deployment has an address of its own.
        timeout: Seconds, or an :class:`httpx.Timeout`. Defaults to 30 seconds.
        max_retries: How many times a failed request that is safe to repeat is retried.
        default_headers: Headers sent with every request.
        http_client: An :class:`httpx.AsyncClient` to send requests with, for proxies, custom
            TLS or transports. The Kaiten client never closes a client it did not create.
    """

    components: AsyncComponents
    """Components: the versioned building blocks releases are made of."""

    connectors: AsyncConnectors
    """Connectors: activation and settings of the integrations this deployment offers."""

    customers: AsyncCustomers
    """Customers: the end clients of your product."""

    deployment_zones: AsyncDeploymentZones
    """Deployment zones: the environments instances run in."""

    entitlement_groups: AsyncEntitlementGroups
    """Entitlement groups: named sets of entitlements."""

    entitlements: AsyncEntitlements
    """Entitlements: the catalog of what licenses can grant."""

    feature_flags: AsyncFeatureFlags
    """Feature flags: their definitions. Evaluate them through OpenFeature."""

    instances: AsyncInstances
    """Instances: deployments of your product, their usage and audit trail."""

    integrations: AsyncIntegrations
    """Customers and instances addressed by their identifier in a third-party system."""

    license_families: AsyncLicenseFamilies
    """License families: the products, each resolved to the version it currently serves."""

    licenses: AsyncLicenses
    """Licenses: the versions of a license family, and the entitlement values they grant."""

    metadata_fields: AsyncMetadataFields
    """Metadata fields: the typed fields of instances and deployment zones."""

    releases: AsyncReleases
    """Releases: immutable, versioned sets of components."""

    service_accounts: AsyncServiceAccounts
    """Service accounts and their tokens."""

    def __init__(
        self,
        *,
        token: AsyncCredential | None = None,
        base_url: str | None = None,
        timeout: TimeoutTypes | NotGiven = NOT_GIVEN,
        max_retries: int = DEFAULT_MAX_RETRIES,
        default_headers: Mapping[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        credential = token if token is not None else os.environ.get(ENV_TOKEN)
        if credential is None or (isinstance(credential, str) and not credential.strip()):
            raise CredentialError(f"No credential: pass token=... or set {ENV_TOKEN}.")
        url = base_url or os.environ.get(ENV_BASE_URL)
        if not url or not url.strip():
            raise ValueError(
                "No Kaiten API address: pass base_url=... (your deployment's, e.g. "
                f"http://localhost:6000) or set {ENV_BASE_URL}."
            )
        self._api = AsyncAPIClient(
            base_url=normalize_base_url(url),
            credential=credential,
            surface="core",
            max_retries=max_retries,
            timeout=timeout,
            default_headers=default_headers,
            http_client=http_client,
        )
        self._bind()

    def _bind(self) -> None:
        api = self._api
        self.components = AsyncComponents(api)
        self.connectors = AsyncConnectors(api)
        self.customers = AsyncCustomers(api)
        self.deployment_zones = AsyncDeploymentZones(api)
        self.entitlement_groups = AsyncEntitlementGroups(api)
        self.entitlements = AsyncEntitlements(api)
        self.feature_flags = AsyncFeatureFlags(api)
        self.instances = AsyncInstances(api)
        self.integrations = AsyncIntegrations(api)
        self.license_families = AsyncLicenseFamilies(api)
        self.licenses = AsyncLicenses(api)
        self.metadata_fields = AsyncMetadataFields(api)
        self.releases = AsyncReleases(api)
        self.service_accounts = AsyncServiceAccounts(api)


class AsyncKaitenPlatformClient(_AsyncBaseClient):
    """Client for the Kaiten Platform API.

    The Platform API administers a deployment across organizations: it ensures
    organizations exist, mints the organization tokens that Core API callers use, and holds
    the connector registry. It listens on its own port, on no public route, and accepts only
    a platform credential (``ksm_...``)::

        async with AsyncKaitenPlatformClient(
            base_url="http://kaiten-api.kaiten.svc:6001", token="ksm_..."
        ) as platform:
            organization = await platform.organizations.ensure(external_id="org_2abcDEF")
            minted = await platform.tokens.mint(organization.id, name="billing-sync")

    Args:
        token: The platform credential, or a callable returning it. Defaults to the
            ``KAITEN_PLATFORM_TOKEN`` environment variable.
        base_url: The Platform API listener -- not the Core API's address, which answers 404
            to every operation here. Defaults to ``KAITEN_PLATFORM_BASE_URL``; required.
        timeout: Seconds, or an :class:`httpx.Timeout`. Defaults to 30 seconds.
        max_retries: How many times a failed request that is safe to repeat is retried.
        default_headers: Headers sent with every request.
        http_client: An :class:`httpx.AsyncClient` to send requests with.
    """

    connectors: AsyncPlatformConnectors
    """The deployment-wide connector registry."""

    organizations: AsyncPlatformOrganizations
    """Organizations: ensure, read, delete, and remove memberships."""

    tokens: AsyncPlatformTokens
    """Organization tokens this platform credential mints, lists and revokes."""

    users: AsyncPlatformUsers
    """Users, across every organization."""

    def __init__(
        self,
        *,
        token: AsyncCredential | None = None,
        base_url: str | None = None,
        timeout: TimeoutTypes | NotGiven = NOT_GIVEN,
        max_retries: int = DEFAULT_MAX_RETRIES,
        default_headers: Mapping[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        credential = token if token is not None else os.environ.get(ENV_PLATFORM_TOKEN)
        if credential is None or (isinstance(credential, str) and not credential.strip()):
            raise CredentialError(
                f"No platform credential: pass token=... or set {ENV_PLATFORM_TOKEN}."
            )
        url = base_url or os.environ.get(ENV_PLATFORM_BASE_URL)
        if not url:
            raise ValueError(
                "The Platform API has no default address: pass base_url=... (its own listener, "
                f"e.g. http://kaiten-api:6001) or set {ENV_PLATFORM_BASE_URL}."
            )
        self._api = AsyncAPIClient(
            base_url=normalize_base_url(url),
            credential=credential,
            surface="platform",
            max_retries=max_retries,
            timeout=timeout,
            default_headers=default_headers,
            http_client=http_client,
        )
        self._bind()

    async def me(self) -> PlatformCredential:
        """Describe the platform credential this client authenticates with.

        Its name, scopes, expiry and identity -- never its value, which exists only at creation.
        Cheap enough to probe a stored credential with: it is the one way to tell a revoked or
        expired credential from a working one without attempting a write.
        """
        return await self._api.get("/platform/me", PlatformCredential)

    def _bind(self) -> None:
        api = self._api
        self.connectors = AsyncPlatformConnectors(api)
        self.organizations = AsyncPlatformOrganizations(api)
        self.tokens = AsyncPlatformTokens(api)
        self.users = AsyncPlatformUsers(api)
