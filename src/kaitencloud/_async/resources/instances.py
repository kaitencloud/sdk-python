# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import builtins
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from ..._constants import EXPORT_MEDIA_TYPES
from ..._exceptions import ThresholdExceededError, TransactionIdReusedError
from ..._models import UsageReportResult
from ..._types import EntitlementValueInput
from ..._utils import (
    api_path,
    check_limit,
    compact,
    format_datetime,
    integration_body,
    integrations_body,
    optional_datetime,
)
from ...types import (
    AuditTrail,
    EntitlementException,
    EntitlementUsage,
    ExceptionKind,
    Instance,
    InstanceIntegration,
    InstanceStatus,
    IntegrationParam,
    ReportedEntitlementUsage,
    UsageBehavior,
    UsageReport,
)
from ._base import AsyncResource

__all__ = ["AsyncInstances"]


class AsyncInstances(AsyncResource):
    """Instances: deployments of your product for a customer, under a license.

    An instance is where entitlements meet reality: usage is reported against it, and its
    audit trail records what happened to it.
    """

    async def list(self) -> builtins.list[Instance]:
        """Return every instance, walking all pages."""
        return await self._api.list_all("/instances", Instance)

    async def get(self, instance_slug: str) -> Instance:
        """Return the instance identified by ``instance_slug``."""
        return await self._api.get(api_path("instances", instance_slug), Instance)

    async def create(
        self,
        *,
        name: str,
        customer_id: str,
        license_id: str,
        start_license_date: datetime | str,
        end_license_date: datetime | str,
        description: str = "",
        deployment_zone_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        slug: str | None = None,
        integrations: Mapping[str, IntegrationParam] | None = None,
    ) -> Instance:
        """Create an instance.

        Args:
            name: The instance's name.
            customer_id: The id -- not the slug -- of the customer it is deployed for.
            license_id: The id of the license it runs under.
            start_license_date: When its license term starts: a timezone-aware datetime, or an
                RFC 3339 string.
            end_license_date: When its license term ends.
            description: A description.
            deployment_zone_id: The id of the deployment zone it runs in.
            metadata: Typed metadata, validated against the organization's ``INSTANCE``
                metadata fields.
            slug: Its URL-friendly identifier, generated when omitted.
            integrations: Links to records in third-party systems, keyed by adapter name.
                Only settable here: afterwards, use :meth:`update_integration`.

        Raises:
            NotFoundError: The customer, license or deployment zone does not exist in this
                organization.
            ConflictError: The slug is taken, or the organization reached its instance limit.
        """
        body = {
            **_instance(
                name=name,
                customer_id=customer_id,
                license_id=license_id,
                start_license_date=start_license_date,
                end_license_date=end_license_date,
                description=description,
                deployment_zone_id=deployment_zone_id,
                metadata=metadata,
            ),
            **compact({"slug": slug, "integrations": integrations_body(integrations)}),
        }
        return await self._api.send("POST", "/instances", Instance, body=body)

    async def update(
        self,
        instance_slug: str,
        *,
        name: str,
        customer_id: str,
        license_id: str,
        start_license_date: datetime | str,
        end_license_date: datetime | str,
        description: str = "",
        deployment_zone_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        slug: str | None = None,
    ) -> None:
        """Replace an instance's details.

        A full replacement, with two fields where leaving a value out keeps the current one:
        ``deployment_zone_id`` and ``slug``. Passing a ``slug`` renames the instance.
        ``metadata`` replaces the whole blob, so send back the keys to keep.

        Moving an instance into a deployment zone, or to another one, is how a deployment or a
        migration is recorded: there is no separate call for either.
        """
        body = {
            **_instance(
                name=name,
                customer_id=customer_id,
                license_id=license_id,
                start_license_date=start_license_date,
                end_license_date=end_license_date,
                description=description,
                deployment_zone_id=deployment_zone_id,
                metadata=metadata,
            ),
            **compact({"slug": slug}),
        }
        await self._api.send_empty("PUT", api_path("instances", instance_slug), body=body)

    async def update_status(self, instance_slug: str, status: InstanceStatus) -> None:
        """Set an instance's operational status, leaving everything else untouched.

        ``status`` is ``HEALTHY``, ``DEGRADED``, ``INCIDENT`` or ``MAINTENANCE``.
        """
        await self._api.send_empty(
            "PATCH", api_path("instances", instance_slug), body={"status": status}, idempotent=True
        )

    async def update_lifecycle_stage(self, instance_slug: str, lifecycle_stage: str) -> None:
        """Set an instance's commercial lifecycle stage, leaving everything else untouched.

        Free-form; ``TRIAL``, ``ACTIVE``, ``AT_RISK`` and ``CHURNED`` are the suggested stages.
        """
        await self._api.send_empty(
            "PATCH",
            api_path("instances", instance_slug),
            body={"lifecycleStage": lifecycle_stage},
            idempotent=True,
        )

    async def delete(self, instance_slug: str) -> None:
        """Delete the instance identified by ``instance_slug``. The deletion is permanent."""
        await self._api.send_empty("DELETE", api_path("instances", instance_slug))

    async def list_audit_trails(
        self,
        instance_slug: str,
        *,
        event_name: str | None = None,
        after: datetime | str | None = None,
        before: datetime | str | None = None,
        limit: int | None = None,
    ) -> builtins.list[AuditTrail]:
        """Return an instance's audit trail entries.

        The audit trail grows without bound, so ``limit`` is a ceiling rather than a page
        size: pages are walked until that many entries are held, and no page asks for more
        than are still wanted. Without a limit, every entry is returned.

        Args:
            instance_slug: The instance whose audit trail to read.
            event_name: Only entries of this event, e.g. ``"INSTANCE_STATUS_CHANGED"``.
            after: Only entries at or after this moment.
            before: Only entries at or before this moment.
            limit: The most entries to return.
        """
        if limit is not None and limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")
        return await self._api.list_all(
            api_path("instances", instance_slug, "audit-trails"),
            AuditTrail,
            params={
                "event_name": event_name,
                "after": optional_datetime(after),
                "before": optional_datetime(before),
            },
            limit=limit,
        )

    async def list_usage(self, instance_slug: str) -> builtins.list[EntitlementUsage]:
        """Return the instance's usage of every entitlement, each next to the grant it counts against."""
        return await self._api.get_list(
            api_path("instances", instance_slug, "entitlements", "usage"), EntitlementUsage
        )

    async def get_usage(self, instance_slug: str, entitlement_slug: str) -> EntitlementUsage:
        """Return the instance's usage of one entitlement, next to the grant it counts against.

        For a periodic entitlement, ``current_period_start`` and ``current_period_end`` bound
        the window the usage belongs to; both are ``None`` for a lifetime counter. Each read is
        recorded as an ``ENTITLEMENT_VALUE_GET`` event.
        """
        return await self._api.get(
            api_path("instances", instance_slug, "entitlements", entitlement_slug, "usage"),
            EntitlementUsage,
        )

    async def report_usage(
        self,
        instance_slug: str,
        entitlement_slug: str,
        value: float,
        *,
        behavior: UsageBehavior = "append",
        metadata: Mapping[str, Any] | None = None,
    ) -> EntitlementUsage:
        """Report usage of a NUMBER entitlement, and return the usage it results in.

        Args:
            instance_slug: The instance that consumed.
            entitlement_slug: The entitlement consumed.
            value: The amount. With ``behavior="append"`` it is folded into the stored total
                through the entitlement's aggregation method (a sum, by default). With
                ``"set"`` it replaces the total -- which is also how to correct it downwards.
            behavior: ``"append"`` (the default) or ``"set"``.
            metadata: Free-form metadata recorded with the report.

        Raises:
            ThresholdExceededError: The report would take usage past the maximum the license
                allows -- the granted value plus its overage allowance. Nothing was recorded.

        Never retried automatically: a report retried after a lost response would be counted
        twice. :meth:`report_usage_detailed` sends one under an idempotency key, which makes
        sending it again safe.
        """
        return await self._api.send(
            "POST",
            _usage_path(instance_slug, entitlement_slug),
            EntitlementUsage,
            body=_usage_report(value, behavior, metadata),
            errors={409: ThresholdExceededError},
        )

    async def report_usage_detailed(
        self,
        instance_slug: str,
        entitlement_slug: str,
        value: float,
        *,
        behavior: UsageBehavior = "append",
        metadata: Mapping[str, Any] | None = None,
        transaction_id: str | None = None,
    ) -> UsageReportResult:
        """Report usage, under an idempotency key, and return what the API said about it.

        Kaiten applies a report at most once per key, instance and entitlement within its
        idempotency window -- 35 days by default. A report sent again under the same key, with
        the same behavior and value, answers the original report and counts nothing: it comes
        back with ``replayed`` set.

        Args:
            instance_slug: The instance that consumed.
            entitlement_slug: The entitlement consumed.
            value: The amount, as :meth:`report_usage` takes it.
            behavior: ``"append"`` (the default) or ``"set"``.
            metadata: Free-form metadata, stored with the report in the usage history when its
                compact JSON is at most 4 KiB; above, it is dropped and ``metadata_dropped`` set.
                It must hold no personal data.
            transaction_id: The id of the business event the report counts -- 1 to 128 of
                letters, digits, ``.``, ``_``, ``:`` and ``-``, e.g. ``"llm-call-9f2c:tokens"``.
                Sent as the ``Idempotency-Key`` header.

        Raises:
            ThresholdExceededError: The report would take usage past the maximum the license
                allows. Nothing was recorded.
            TransactionIdReusedError: The key was spent on a report with another behavior or
                value. Nothing was recorded.

        Never retried automatically, key or not: a Kaiten older than keys ignores the header and
        would count a resent report twice. Resend it yourself, under the same key.
        """
        try:
            response = await self._api.request(
                "POST",
                _usage_path(instance_slug, entitlement_slug),
                body=_usage_report(value, behavior, metadata),
                headers=compact({"Idempotency-Key": transaction_id}),
                errors={409: ThresholdExceededError},
            )
        except ThresholdExceededError as error:
            # The usage endpoint answers 409 for two reasons; only the code tells them apart.
            if error.code == "ReportEntitlementUsageMetric.TransactionIdReused":
                raise TransactionIdReusedError(
                    str(error), response=error.response, problem=error.problem
                ) from None
            raise
        return UsageReportResult(
            usage=self._api.validate(
                ReportedEntitlementUsage, self._api.decode(response), response
            ),
            replayed=response.headers.get("Idempotent-Replayed") == "true",
            metadata_dropped=bool(response.headers.get("Kaiten-Metadata-Dropped")),
        )

    async def list_usage_reports(
        self,
        instance_slug: str,
        entitlement_slug: str,
        *,
        from_: datetime | str | None = None,
        to: datetime | str | None = None,
        transaction_id: str | None = None,
        limit: int | None = None,
    ) -> builtins.list[UsageReport]:
        """Return the usage history of one entitlement for an instance, oldest report first.

        Every report the API accepted in the range, with the counter before and after it and
        the limit in force. Decimals are strings, exact to the digit. Reports are kept for the
        organization's usage history retention.

        Args:
            instance_slug: The instance.
            entitlement_slug: The entitlement.
            from_: Start of the range, inclusive. Defaults to 30 days before ``to``; a moment
                before the usage history starts is refused (``ListUsageReports.OutsideRetention``).
            to: End of the range, exclusive. Defaults to now.
            transaction_id: Only the report sent with this key.
            limit: The most reports to return. Every page is walked when omitted.
        """
        return await self._api.list_reports(
            api_path(
                "instances", instance_slug, "entitlements", entitlement_slug, "usage", "reports"
            ),
            UsageReport,
            params={
                "from": optional_datetime(from_),
                "to": optional_datetime(to),
                "transactionId": transaction_id,
            },
            limit=check_limit(limit),
        )

    async def export_usage_reports(
        self,
        instance_slug: str,
        entitlement_slug: str,
        *,
        from_: datetime | str | None = None,
        to: datetime | str | None = None,
        format: Literal["csv", "json"] = "csv",
    ) -> bytes:
        """Return the usage history of one entitlement for an instance, exported.

        At most 366 days per call, decimals written exactly as the journal stores them.

        Args:
            instance_slug: The instance.
            entitlement_slug: The entitlement.
            from_: Start of the range, inclusive (see :meth:`list_usage_reports`).
            to: End of the range, exclusive. Defaults to now.
            format: ``"csv"`` (the default), RFC 4180 with a header row, or ``"json"`` for
                NDJSON, one report per line in the shape :meth:`list_usage_reports` returns.
        """
        response = await self._api.request(
            "GET",
            api_path(
                "instances",
                instance_slug,
                "entitlements",
                entitlement_slug,
                "usage",
                "reports",
                "export",
            ),
            params={
                "from": optional_datetime(from_),
                "to": optional_datetime(to),
                "format": format,
            },
            headers={"Accept": EXPORT_MEDIA_TYPES[format]},
        )
        return response.content

    async def export_organization_usage_reports(
        self,
        *,
        from_: datetime | str | None = None,
        to: datetime | str | None = None,
        format: Literal["csv", "json"] = "csv",
        instance_slug: str | None = None,
        instance_id: str | None = None,
        entitlement_slug: str | None = None,
        entitlement_id: str | None = None,
    ) -> bytes:
        """Return the whole organization's usage history, exported, ordered by acceptance.

        Every instance and entitlement, at most 31 days per call: keep it before deleting the
        organization. ``instance_id`` and ``entitlement_id`` reach deleted ones, whose reports
        are kept.

        Args:
            from_: Start of the range, inclusive (see :meth:`list_usage_reports`).
            to: End of the range, exclusive. Defaults to now.
            format: ``"csv"`` (the default) or ``"json"`` for NDJSON.
            instance_slug: Only this instance.
            instance_id: Only this instance, by id.
            entitlement_slug: Only this entitlement.
            entitlement_id: Only this entitlement, by id.
        """
        response = await self._api.request(
            "GET",
            "/usage/reports/export",
            params={
                "from": optional_datetime(from_),
                "to": optional_datetime(to),
                "format": format,
                "instanceSlug": instance_slug,
                "instanceId": instance_id,
                "entitlementSlug": entitlement_slug,
                "entitlementId": entitlement_id,
            },
            headers={"Accept": EXPORT_MEDIA_TYPES[format]},
        )
        return response.content

    async def list_entitlement_exceptions(
        self, instance_slug: str, *, include_inactive: bool = False
    ) -> builtins.list[EntitlementException]:
        """Return the instance's entitlement exceptions, latest start first, with their status.

        Args:
            instance_slug: The instance.
            include_inactive: Also return the revoked and ended ones. Only the active and the
                scheduled ones otherwise.
        """
        return await self._api.get_list(
            api_path("instances", instance_slug, "entitlement-exceptions"),
            EntitlementException,
            params={"filter": "all" if include_inactive else None},
        )

    async def create_entitlement_exception(
        self,
        instance_slug: str,
        entitlement_slug: str,
        *,
        kind: ExceptionKind,
        reason: str,
        value: EntitlementValueInput | None = None,
        starts_at: datetime | str | None = None,
        ends_at: datetime | str | None = None,
    ) -> EntitlementException:
        """Override one entitlement of an instance, for a while, and return the exception.

        An exception is your explicit, dated decision on one instance: the last layer of its
        effective entitlements, after the license, the add-ons and the boosts. It wins over
        them, and may lower the value. An instance has one unrevoked exception per entitlement
        at any moment. It works whether or not billing is enabled.

        Args:
            instance_slug: The instance.
            entitlement_slug: The entitlement it overrides, granted or not.
            kind: ``SET`` works on every type; ``ADD`` and ``UNLIMITED`` on numbers only.
            reason: Why, 1 to 500 characters, shown to you only.
            value: For ``SET``, a number of 0 or more, a ``bool`` or a mapping, by the
                entitlement's type; for ``ADD``, a number above 0; nothing for ``UNLIMITED``.
            starts_at: When it starts: now when omitted; a future moment schedules it.
            ends_at: When it ends. It never does when omitted.
        """
        body = {
            "entitlementSlug": entitlement_slug,
            "kind": kind,
            "reason": reason,
            **compact(
                {
                    "value": dict(value) if isinstance(value, Mapping) else value,
                    "startsAt": optional_datetime(starts_at),
                    "endsAt": optional_datetime(ends_at),
                }
            ),
        }
        return await self._api.send(
            "POST",
            api_path("instances", instance_slug, "entitlement-exceptions"),
            EntitlementException,
            body=body,
        )

    async def revoke_entitlement_exception(self, instance_slug: str, exception_id: str) -> None:
        """Revoke an exception, which is kept: a scheduled one never starts, an active one ends.

        Revoking one already revoked or ended changes nothing.
        """
        await self._api.send_empty(
            "DELETE", api_path("instances", instance_slug, "entitlement-exceptions", exception_id)
        )

    async def get_integration(
        self, instance_slug: str, integration_name: str
    ) -> InstanceIntegration:
        """Return the instance's link to the ``integration_name`` adapter."""
        return await self._api.get(
            api_path("instances", instance_slug, "integrations", integration_name),
            InstanceIntegration,
        )

    async def create_integration(
        self,
        instance_slug: str,
        integration_name: str,
        *,
        external_id: str,
        metadata: Mapping[str, Any] | None = None,
        web_url: str | None = None,
        last_error: str | None = None,
    ) -> InstanceIntegration:
        """Link the instance to a record in the ``integration_name`` adapter.

        Args:
            instance_slug: The instance to link.
            integration_name: The adapter, e.g. ``"attio"``.
            external_id: The record's identifier in the third-party system.
            metadata: Adapter-specific metadata.
            web_url: An absolute http(s) link to the record.
            last_error: The last synchronization error, if any.
        """
        return await self._api.send(
            "POST",
            api_path("instances", instance_slug, "integrations", integration_name),
            InstanceIntegration,
            body=integration_body(
                external_id=external_id, metadata=metadata, web_url=web_url, last_error=last_error
            ),
        )

    async def update_integration(
        self,
        instance_slug: str,
        integration_name: str,
        *,
        external_id: str,
        metadata: Mapping[str, Any] | None = None,
        web_url: str | None = None,
        last_error: str | None = None,
    ) -> InstanceIntegration:
        """Replace the instance's link to the ``integration_name`` adapter, and return it."""
        return await self._api.send(
            "PUT",
            api_path("instances", instance_slug, "integrations", integration_name),
            InstanceIntegration,
            body=integration_body(
                external_id=external_id, metadata=metadata, web_url=web_url, last_error=last_error
            ),
        )

    async def delete_integration(self, instance_slug: str, integration_name: str) -> None:
        """Remove the instance's link to the ``integration_name`` adapter."""
        await self._api.send_empty(
            "DELETE", api_path("instances", instance_slug, "integrations", integration_name)
        )


def _instance(
    *,
    name: str,
    customer_id: str,
    license_id: str,
    start_license_date: datetime | str,
    end_license_date: datetime | str,
    description: str,
    deployment_zone_id: str | None,
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "customerId": customer_id,
        "licenseId": license_id,
        "startLicenseDate": format_datetime(start_license_date),
        "endLicenseDate": format_datetime(end_license_date),
        **compact(
            {
                "deploymentZoneId": deployment_zone_id,
                "metadata": dict(metadata) if metadata is not None else None,
            }
        ),
    }


def _usage_path(instance_slug: str, entitlement_slug: str) -> str:
    return api_path("instances", instance_slug, "entitlements", entitlement_slug, "usage")


def _usage_report(
    value: float, behavior: UsageBehavior, metadata: Mapping[str, Any] | None
) -> dict[str, Any]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"usage must be a number, got {type(value).__name__}")
    return compact(
        {
            "value": {"type": "number", "value": value},
            "behavior": behavior,
            "metadata": dict(metadata) if metadata is not None else None,
        }
    )
