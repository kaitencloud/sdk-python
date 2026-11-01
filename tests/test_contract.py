# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Every SDK method, checked against the contract operation it calls.

Each case calls a method against a fake API that answers the way the contract describes -- the
operation's success status, with a payload generated from its response schema -- then checks
what went on the wire:

- the request addresses the operation the method is mapped to, under ``/api``;
- its query parameters are ones that operation declares;
- its body validates against the operation's request schema with the write-side rules
  applied: no readOnly property, and every required writable one. Every Kaiten request body
  is ``additionalProperties: false``, so a key too many and a required key missing end the
  same way -- a 422 on every call, with no type error to catch it;
- the rules the schema cannot express hold: a slug an update refuses, a license version a
  create refuses;
- the credential travels where the operation's security scheme says: a bearer token, or a
  publishable key in its own header.

A ``-minimal`` variant calls the method with its required arguments only, which is where a
required-but-nullable key left out would show. Both clients run the whole table: the async
source, and the sync client generated from it. Along the way every response model parses a
payload shaped like the contract's, since each call returns one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from contract import Operation, contract_api, document, find_operation, write_errors
from helpers import ORG_ID, USER_ID, Recorder, body

from kaitencloud import targeting

ID = "5d1e8f3a-2b4c-4d6e-8f0a-1b2c3d4e5f60"
SAMPLE_ID = "0f9e8d7c-6b5a-4938-8271-605f4e3d2c1b"
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=30)
CONNECTOR = "kaiten.integration.crm.attio"
INTEGRATION = {
    "external_id": "rec_1",
    "metadata": {"stage": "won"},
    "web_url": "https://app.attio.com/rec_1",
    "last_error": "timeout",
}
VARIANTS = [targeting.variant("on", True, description="Enabled"), targeting.variant("off", False)]
VOUCHER: dict[str, Any] = {
    "name": "Welcome",
    "voucher_type": "COMPOSITE",
    "duration": "REPEATING",
    "code": "WELCOME-2026",
    "description": "First three months at 20% off, and ten more seats",
    "duration_in_periods": 3,
    "starts_at": NOW,
    "expires_at": LATER,
    "max_redemptions": 100,
    "restricted_customer_slug": "acme",
    "price_discount_type": "PERCENTAGE",
    "price_discount_value": "20",
    "price_applies_to": "SELECTED_PRICES",
    "applicable_license_ids": [ID],
    "applicable_license_price_ids": [ID],
    "applicable_addon_ids": [SAMPLE_ID],
    "applicable_addon_price_ids": [SAMPLE_ID],
    "grants": [{"entitlementSlug": "seats", "modifierType": "ADD", "modifierValue": "10"}],
    "flag_grants": {"new-checkout": "on"},
    "redemption_rules": {
        "annualOnly": True,
        "firstTimeOnly": True,
        "minimumSubscriptionAmount": {"currency": "EUR", "unitAmountDecimal": "1000"},
    },
}
RULES = [
    targeting.rule("Growth plan", "__kaiten.license.slug == 'growth'", "on"),
    targeting.split_rule("Progressive rollout", "true", {"on": 20, "off": 80}),
    targeting.schedule_rule(
        "Launch", "true", start=targeting.step("on", 0, NOW), end=targeting.step("on", 100, LATER)
    ),
]


@dataclass(frozen=True)
class Case:
    operation_id: str
    call: Callable[[Any], Any]
    minimal: Callable[[Any], Any] | None = None
    forbidden: frozenset[str] = frozenset()
    required: frozenset[str] = frozenset()
    surface: str = "core"
    name: str = ""
    token: str | None = None


CASES = [
    # components
    Case("list-components", lambda c: c.components.list()),
    Case("get-component", lambda c: c.components.get("api-gateway")),
    Case(
        "create-component",
        lambda c: c.components.create(
            name="api-gateway",
            version="v1.2.3",
            description="Edge proxy",
            previous_component_id=ID,
            slug="api-gateway",
        ),
        minimal=lambda c: c.components.create(name="api-gateway", version="v1.2.3"),
    ),
    Case(
        "update-component",
        lambda c: c.components.update(
            "api-gateway", name="api-gateway", version="v1.2.4", description="Edge proxy"
        ),
        minimal=lambda c: c.components.update("api-gateway", name="api-gateway", version="v1.2.4"),
        forbidden=frozenset({"slug", "previousComponentId"}),
    ),
    Case("delete-component", lambda c: c.components.delete("api-gateway")),
    # connectors
    Case("list-connectors", lambda c: c.connectors.list()),
    Case("get-connector", lambda c: c.connectors.get(CONNECTOR)),
    Case("get-connector-state", lambda c: c.connectors.get_state(CONNECTOR)),
    Case("activate-connector", lambda c: c.connectors.activate(CONNECTOR)),
    Case("deactivate-connector", lambda c: c.connectors.deactivate(CONNECTOR)),
    Case("get-connector-settings-schema", lambda c: c.connectors.get_settings_schema(CONNECTOR)),
    Case("get-connector-settings", lambda c: c.connectors.get_settings(CONNECTOR)),
    Case(
        "update-connector-settings",
        lambda c: c.connectors.update_settings(CONNECTOR, {"apiKey": "secret"}),
        forbidden=frozenset({"connector_name"}),
    ),
    Case("delete-connector-settings", lambda c: c.connectors.delete_settings(CONNECTOR)),
    # customers
    Case("list-customers", lambda c: c.customers.list()),
    Case("get-customer", lambda c: c.customers.get("acme")),
    Case(
        "create-customer",
        lambda c: c.customers.create(
            name="Acme",
            slug="acme",
            external_customer_id="crm-42",
            domain="acme.com",
            integrations={"attio": INTEGRATION},
            billing_email="billing@acme.com",
        ),
        minimal=lambda c: c.customers.create(name="Acme"),
    ),
    Case(
        "update-customer",
        lambda c: c.customers.update(
            "acme",
            name="Acme Corp",
            external_customer_id="crm-42",
            domain="acme.com",
            billing_email="billing@acme.com",
        ),
        minimal=lambda c: c.customers.update("acme", name="Acme Corp"),
        forbidden=frozenset({"slug", "integrations"}),
    ),
    Case("delete-customer", lambda c: c.customers.delete("acme")),
    Case("get-customer-integration", lambda c: c.customers.get_integration("acme", "attio")),
    Case(
        "create-customer-integration",
        lambda c: c.customers.create_integration("acme", "attio", **INTEGRATION),
        minimal=lambda c: c.customers.create_integration("acme", "attio", external_id="rec_1"),
    ),
    Case(
        "update-customer-integration",
        lambda c: c.customers.update_integration("acme", "attio", **INTEGRATION),
        minimal=lambda c: c.customers.update_integration("acme", "attio", external_id="rec_1"),
    ),
    Case("delete-customer-integration", lambda c: c.customers.delete_integration("acme", "attio")),
    # deployment zones
    Case("list-deployment-zones", lambda c: c.deployment_zones.list()),
    Case("get-deployment-zone-by-slug", lambda c: c.deployment_zones.get("eu-west-1")),
    Case(
        "create-deployment-zone",
        lambda c: c.deployment_zones.create(
            name="AWS eu-west-1",
            type="production",
            description="Primary region",
            metadata={"region": "eu-west-1"},
            release_id=ID,
            slug="eu-west-1",
        ),
        minimal=lambda c: c.deployment_zones.create(name="AWS eu-west-1", type="production"),
    ),
    Case(
        "update-deploymentZone",
        lambda c: c.deployment_zones.update(
            "eu-west-1",
            name="AWS eu-west-1",
            type="production",
            description="Primary region",
            metadata={"region": "eu-west-1"},
            release_id=ID,
        ),
        minimal=lambda c: c.deployment_zones.update(
            "eu-west-1", name="AWS eu-west-1", type="production"
        ),
        forbidden=frozenset({"slug"}),
    ),
    Case("delete-deployment-zone", lambda c: c.deployment_zones.delete("eu-west-1")),
    # entitlement groups
    Case("list-entitlement-groups", lambda c: c.entitlement_groups.list()),
    Case("get-entitlement-group", lambda c: c.entitlement_groups.get("ai-quotas")),
    Case(
        "create-entitlement-group",
        lambda c: c.entitlement_groups.create(
            name="AI quotas", description="Everything AI", slug="ai-quotas"
        ),
        minimal=lambda c: c.entitlement_groups.create(name="AI quotas"),
        required=frozenset({"description"}),
    ),
    Case(
        "update-entitlement-group",
        lambda c: c.entitlement_groups.update(
            "ai-quotas", name="AI quotas", description="Everything AI"
        ),
        minimal=lambda c: c.entitlement_groups.update("ai-quotas", name="AI quotas"),
        forbidden=frozenset({"slug"}),
        required=frozenset({"description"}),
    ),
    Case("delete-entitlement-group", lambda c: c.entitlement_groups.delete("ai-quotas")),
    Case(
        "add-entitlement-to-group",
        lambda c: c.entitlement_groups.add_entitlement("ai-quotas", "tokens"),
    ),
    Case(
        "remove-entitlement-from-group",
        lambda c: c.entitlement_groups.remove_entitlement("ai-quotas", "tokens"),
    ),
    Case(
        "get-entitlement-group-usage",
        lambda c: c.entitlement_groups.get_usage("ai-quotas", "acme-production"),
    ),
    # entitlements
    Case("list-entitlements", lambda c: c.entitlements.list()),
    Case("get-entitlement", lambda c: c.entitlements.get("seats")),
    Case(
        "create-entitlement",
        lambda c: c.entitlements.create(
            name="Seats",
            type="NUMBER",
            description="Named users",
            slug="seats",
            aggregation_method="SUM",
            reset_period="MONTH",
            reset_anchor="CALENDAR",
            warning_threshold_percent=80,
            group_slugs=["core"],
            user_facing=True,
            display_order=10,
            icon="lucide:users",
            unit_singular="seat",
            unit_plural="seats",
            sale_unit_singular="pack",
            sale_unit_plural="packs",
            sale_unit_factor=10.0,
        ),
        minimal=lambda c: c.entitlements.create(name="Seats"),
        required=frozenset({"description"}),
    ),
    Case(
        "update-entitlement",
        lambda c: c.entitlements.update(
            "seats",
            name="Seats",
            type="NUMBER",
            description="Named users",
            aggregation_method="SUM",
            reset_period="MONTH",
            reset_anchor="CALENDAR",
            warning_threshold_percent=80,
            group_slugs=["core"],
            user_facing=True,
            display_order=10,
            icon="lucide:users",
            unit_singular="seat",
            unit_plural="seats",
            sale_unit_singular="pack",
            sale_unit_plural="packs",
            sale_unit_factor=10.0,
        ),
        minimal=lambda c: c.entitlements.update("seats", name="Seats"),
        forbidden=frozenset({"slug"}),
        required=frozenset({"description"}),
    ),
    Case("delete-entitlement", lambda c: c.entitlements.delete("seats")),
    # feature flags
    Case("get-feature-flags", lambda c: c.feature_flags.list()),
    Case("get-feature-flag", lambda c: c.feature_flags.get("new-checkout")),
    Case(
        "create-feature-flag",
        lambda c: c.feature_flags.create(
            name="New checkout",
            type="boolean",
            variants=VARIANTS,
            default_variant=targeting.split({"on": 10, "off": 90}),
            targetings=RULES,
            enabled=False,
            description="The redesigned checkout",
            metadata={"team": "growth"},
            event_name="checkout_viewed",
            slug="new-checkout",
        ),
        minimal=lambda c: c.feature_flags.create(
            name="New checkout", type="boolean", variants=VARIANTS, default_variant="off"
        ),
    ),
    Case(
        "update-feature-flag",
        lambda c: c.feature_flags.update(
            "new-checkout",
            name="New checkout",
            type="boolean",
            variants=VARIANTS,
            default_variant=targeting.schedule(
                start=targeting.step("on", 0, NOW), end=targeting.step("on", 100, LATER)
            ),
            targetings=RULES,
            enabled=True,
            description="The redesigned checkout",
            metadata={"team": "growth"},
            event_name="checkout_viewed",
        ),
        minimal=lambda c: c.feature_flags.update(
            "new-checkout",
            name="New checkout",
            type="boolean",
            variants=VARIANTS,
            default_variant=targeting.fixed("off"),
        ),
        required=frozenset({"slug"}),
    ),
    Case("delete-feature-flag", lambda c: c.feature_flags.delete("new-checkout")),
    Case("get-openfeature-manifest", lambda c: c.feature_flags.manifest()),
    Case("get-targeting-context", lambda c: c.feature_flags.targeting_context()),
    Case(
        "lint-targeting-rule",
        lambda c: c.feature_flags.lint_rule("__kaiten.license.slug == 'growth'"),
        required=frozenset({"rule"}),
    ),
    Case(
        "test-targeting-rule",
        lambda c: c.feature_flags.test_rule(
            "__kaiten.instance.status == 'HEALTHY'",
            targeting_key="acme",
            context={"kaiten": {"instanceSlug": "acme-production"}},
        ),
        minimal=lambda c: c.feature_flags.test_rule("true"),
        required=frozenset({"rule"}),
    ),
    # instances
    Case("getInstances", lambda c: c.instances.list()),
    Case("getInstance", lambda c: c.instances.get("acme-production")),
    Case(
        "createInstance",
        lambda c: c.instances.create(
            name="Acme production",
            customer_id=ID,
            license_id=ID,
            start_license_date=NOW,
            end_license_date=LATER,
            description="Dedicated cluster",
            deployment_zone_id=ID,
            metadata={"tier": "gold"},
            slug="acme-production",
            integrations={"attio": INTEGRATION},
        ),
        minimal=lambda c: c.instances.create(
            name="Acme production",
            customer_id=ID,
            license_id=ID,
            start_license_date=NOW,
            end_license_date=LATER,
        ),
    ),
    Case(
        "updateInstance",
        lambda c: c.instances.update(
            "acme-production",
            name="Acme production",
            customer_id=ID,
            license_id=ID,
            start_license_date=NOW,
            end_license_date=LATER,
            description="Dedicated cluster",
            deployment_zone_id=ID,
            metadata={"tier": "gold"},
            slug="acme-prod",
        ),
        minimal=lambda c: c.instances.update(
            "acme-production",
            name="Acme production",
            customer_id=ID,
            license_id=ID,
            start_license_date="2026-09-14T12:00:00Z",
            end_license_date="2027-09-14T12:00:00Z",
        ),
        forbidden=frozenset({"integrations"}),
    ),
    Case(
        "patchInstance",
        lambda c: c.instances.update_status("acme-production", "DEGRADED"),
        name="patchInstance-status",
    ),
    Case(
        "patchInstance",
        lambda c: c.instances.update_lifecycle_stage("acme-production", "AT_RISK"),
        name="patchInstance-lifecycle_stage",
    ),
    Case("deleteInstance", lambda c: c.instances.delete("acme-production")),
    Case(
        "getAuditTrails",
        lambda c: c.instances.list_audit_trails(
            "acme-production",
            event_name="INSTANCE_STATUS_CHANGED",
            after=NOW,
            before=LATER,
            limit=10,
        ),
        minimal=lambda c: c.instances.list_audit_trails("acme-production"),
    ),
    Case("getEntitlementsUsageMetrics", lambda c: c.instances.list_usage("acme-production")),
    Case("getEntitlementUsageMetrics", lambda c: c.instances.get_usage("acme-production", "seats")),
    Case(
        "reportEntitlementUsageMetric",
        lambda c: c.instances.report_usage(
            "acme-production", "seats", 3, behavior="set", metadata={"source": "billing"}
        ),
        minimal=lambda c: c.instances.report_usage("acme-production", "seats", 1),
    ),
    Case(
        "get-instance-integration",
        lambda c: c.instances.get_integration("acme-production", "attio"),
    ),
    Case(
        "create-instance-integration",
        lambda c: c.instances.create_integration("acme-production", "attio", **INTEGRATION),
        minimal=lambda c: c.instances.create_integration(
            "acme-production", "attio", external_id="rec_1"
        ),
    ),
    Case(
        "update-instance-integration",
        lambda c: c.instances.update_integration("acme-production", "attio", **INTEGRATION),
        minimal=lambda c: c.instances.update_integration(
            "acme-production", "attio", external_id="rec_1"
        ),
    ),
    Case(
        "delete-instance-integration",
        lambda c: c.instances.delete_integration("acme-production", "attio"),
    ),
    # integrations by external id
    Case(
        "get-customer-integration-by-external-id",
        lambda c: c.integrations.get_customer("attio", "rec_1"),
    ),
    Case(
        "upsert-customer-integration-by-external-id",
        lambda c: c.integrations.upsert_customer(
            "attio",
            "rec_1",
            name="Acme",
            slug="acme",
            domain="acme.com",
            web_url="https://app.attio.com/rec_1",
            error="timeout",
            integration_metadata={"stage": "won"},
        ),
        minimal=lambda c: c.integrations.upsert_customer("attio", "rec_1"),
    ),
    Case(
        "get-instance-integration-by-external-id",
        lambda c: c.integrations.get_instance("attio", "rec_9"),
    ),
    Case(
        "upsert-instance-integration-by-external-id",
        lambda c: c.integrations.upsert_instance(
            "attio",
            "rec_9",
            name="Acme production",
            slug="acme-production",
            description="Dedicated cluster",
            customer_external_id="rec_1",
            license_id=ID,
            deployment_zone_id=ID,
            start_license_date=NOW,
            end_license_date=LATER,
            metadata={"tier": "gold"},
            web_url="https://app.attio.com/rec_9",
            error="timeout",
            integration_metadata={"stage": "live"},
        ),
        minimal=lambda c: c.integrations.upsert_instance("attio", "rec_9"),
    ),
    # licenses
    Case("get-licenses", lambda c: c.licenses.list()),
    Case("get-license", lambda c: c.licenses.get("growth")),
    Case(
        "create-license",
        lambda c: c.licenses.create(
            name="Growth",
            type="PAID",
            description="For scaling teams",
            is_default=True,
            version_name="Winter 2026",
            slug="growth-v2",
            family_slug="growth",
            family_id=ID,
            lifecycle_state="PUBLISHED",
            pricing_type="PAID",
            trial_period_days=14,
            requires_payment_method=True,
            self_serve_cta_url="https://acme.com/contact",
        ),
        minimal=lambda c: c.licenses.create(name="Growth", type="PAID"),
        forbidden=frozenset({"version"}),
    ),
    Case(
        "create-license",
        lambda c: c.licenses.create(
            name="Growth", type="PAID", family_slug="growth", lifecycle_state="DRAFT"
        ),
        forbidden=frozenset({"version", "familyId"}),
        required=frozenset({"familySlug", "lifecycleState"}),
        name="create-license-draft-version",
    ),
    Case(
        "update-license",
        lambda c: c.licenses.update(
            "growth-v2",
            name="Growth",
            type="PAID",
            description="For scaling teams",
            is_default=True,
            version_name="Winter 2026",
            pricing_type="CUSTOM",
            trial_period_days=0,
            requires_payment_method=False,
            self_serve_cta_url="",
        ),
        minimal=lambda c: c.licenses.update("growth-v2", name="Growth", type="PAID"),
        # a version never changes family or number, and moves state only through the
        # lifecycle operations below: none of it belongs in an update
        forbidden=frozenset({"slug", "version", "familySlug", "familyId", "lifecycleState"}),
    ),
    Case("delete-license", lambda c: c.licenses.delete("growth-v2")),
    Case("publish-license", lambda c: c.licenses.publish("growth-v2")),
    Case("archive-license", lambda c: c.licenses.archive("growth-v2")),
    Case("unarchive-license", lambda c: c.licenses.unarchive("growth-v2")),
    # license families
    Case("list-license-families", lambda c: c.license_families.list()),
    Case(
        "get-license-family",
        lambda c: c.license_families.get("growth", version=2, include_versions=True),
        minimal=lambda c: c.license_families.get("growth"),
    ),
    Case("get-license-entitlements", lambda c: c.licenses.list_entitlements("growth")),
    Case("get-license-entitlement", lambda c: c.licenses.get_entitlement("growth", "seats")),
    Case(
        "associate-entitlement-with-license",
        lambda c: c.licenses.associate_entitlement("growth", "seats", 50, overage_percent=10),
        minimal=lambda c: c.licenses.associate_entitlement("growth", "sso", True),
        required=frozenset({"entitlementSlug", "value"}),
    ),
    Case(
        "update-license-entitlement",
        lambda c: c.licenses.update_entitlement(
            "growth", "branding", {"logo": True}, overage_percent=0
        ),
        minimal=lambda c: c.licenses.update_entitlement("growth", "seats", -1),
        forbidden=frozenset({"entitlementSlug"}),
    ),
    Case("delete-license-entitlement", lambda c: c.licenses.delete_entitlement("growth", "seats")),
    # metadata fields
    Case(
        "list-metadata-fields",
        lambda c: c.metadata_fields.list("INSTANCE", include_archived=True),
        minimal=lambda c: c.metadata_fields.list("INSTANCE"),
    ),
    Case(
        "create-metadata-field",
        lambda c: c.metadata_fields.create(
            resource_type="INSTANCE",
            key="region",
            label="Region",
            json_schema={"type": "string", "enum": ["eu", "us"]},
            display_order=2,
        ),
        minimal=lambda c: c.metadata_fields.create(
            resource_type="INSTANCE", key="region", label="Region", json_schema={"type": "string"}
        ),
    ),
    Case(
        "update-metadata-field",
        lambda c: c.metadata_fields.update(
            ID,
            resource_type="INSTANCE",
            key="region",
            label="Hosting region",
            json_schema={"type": "string"},
        ),
        forbidden=frozenset({"displayOrder"}),
    ),
    Case("archive-metadata-field", lambda c: c.metadata_fields.archive(ID)),
    Case("unarchive-metadata-field", lambda c: c.metadata_fields.unarchive(ID)),
    Case(
        "dry-run-metadata-field",
        lambda c: c.metadata_fields.dry_run(ID, {"type": "string", "enum": ["eu"]}),
    ),
    Case("reorder-metadata-fields", lambda c: c.metadata_fields.reorder([ID, SAMPLE_ID])),
    # releases
    Case("list-releases", lambda c: c.releases.list()),
    Case("get-release-by-slug", lambda c: c.releases.get("v1-4-0")),
    Case(
        "create-release",
        lambda c: c.releases.create(
            version="v1.4.0", description="Faster sync", component_ids=[ID], slug="v1-4-0"
        ),
        minimal=lambda c: c.releases.create(version="v1.4.0"),
    ),
    Case("delete-release", lambda c: c.releases.delete("v1-4-0")),
    # service accounts
    Case("get-service-accounts", lambda c: c.service_accounts.list()),
    Case("get-service-account", lambda c: c.service_accounts.get("billing-sync")),
    Case(
        "create-service-account",
        lambda c: c.service_accounts.create(name="Billing sync", slug="billing-sync"),
        minimal=lambda c: c.service_accounts.create(name="Billing sync"),
    ),
    Case(
        "update-service-account",
        lambda c: c.service_accounts.update("billing-sync", name="Billing sync"),
        forbidden=frozenset({"slug"}),
    ),
    Case("get-service-account-tokens", lambda c: c.service_accounts.list_tokens("billing-sync")),
    Case(
        "create-service-account-token",
        lambda c: c.service_accounts.create_token(
            "billing-sync",
            name="ci",
            scopes=["read:customers", "write:instances"],
            slug="ci",
            expires_at=LATER,
        ),
        minimal=lambda c: c.service_accounts.create_token("billing-sync", name="ci"),
        required=frozenset({"scopes"}),
    ),
    Case(
        "delete-service-account-token",
        lambda c: c.service_accounts.delete_token("billing-sync", "ci"),
    ),
    # instances: keyed usage reports, the usage history, entitlement exceptions
    Case(
        "reportEntitlementUsageMetric",
        lambda c: c.instances.report_usage_detailed(
            "acme-production",
            "seats",
            3,
            behavior="set",
            metadata={"source": "billing"},
            transaction_id="llm-call-9f2c:tokens",
        ),
        minimal=lambda c: c.instances.report_usage_detailed("acme-production", "seats", 1),
        name="reportEntitlementUsageMetric-detailed",
    ),
    Case(
        "listUsageReports",
        # A ceiling: the fake API answers every page with the same nextAfterSeq.
        lambda c: c.instances.list_usage_reports(
            "acme-production", "seats", from_=NOW, to=LATER, transaction_id="call-1", limit=1
        ),
    ),
    Case(
        "exportUsageReports",
        lambda c: c.instances.export_usage_reports(
            "acme-production", "seats", from_=NOW, to=LATER, format="json"
        ),
        minimal=lambda c: c.instances.export_usage_reports("acme-production", "seats"),
    ),
    Case(
        "exportOrganizationUsageReports",
        lambda c: c.instances.export_organization_usage_reports(
            from_=NOW,
            to=LATER,
            format="json",
            instance_slug="acme-production",
            instance_id=ID,
            entitlement_slug="seats",
            entitlement_id=SAMPLE_ID,
        ),
        minimal=lambda c: c.instances.export_organization_usage_reports(),
    ),
    Case(
        "listEntitlementExceptions",
        lambda c: c.instances.list_entitlement_exceptions("acme-production", include_inactive=True),
        minimal=lambda c: c.instances.list_entitlement_exceptions("acme-production"),
    ),
    Case(
        "createEntitlementException",
        lambda c: c.instances.create_entitlement_exception(
            "acme-production",
            "seats",
            kind="SET",
            reason="Pilot extension",
            value=200,
            starts_at=NOW,
            ends_at=LATER,
        ),
        minimal=lambda c: c.instances.create_entitlement_exception(
            "acme-production", "seats", kind="UNLIMITED", reason="Pilot extension"
        ),
        required=frozenset({"entitlementSlug", "kind", "reason"}),
    ),
    Case(
        "revokeEntitlementException",
        lambda c: c.instances.revoke_entitlement_exception("acme-production", ID),
    ),
    # license families
    Case(
        "updateLicenseFamily",
        lambda c: c.license_families.update(
            "growth",
            is_public=True,
            fallback_license_family_slug="free",
            trial_end_without_payment_method="CANCEL",
            trial_reminder_days=3,
        ),
        minimal=lambda c: c.license_families.update("growth"),
    ),
    # billing
    Case("getBillingSettings", lambda c: c.billing.get_settings()),
    Case(
        "updateBillingSettings",
        lambda c: c.billing.update_settings(
            default_collection_method="SEND_INVOICE",
            default_days_until_due=30,
            handoff_stripe_invoices=False,
        ),
    ),
    Case("getBillingCapabilities", lambda c: c.billing.get_capabilities()),
    Case("getBillingHealth", lambda c: c.billing.get_health()),
    Case("syncBillingProvider", lambda c: c.billing.sync()),
    Case(
        "closeBillingPeriods",
        lambda c: c.billing.close_periods(instance_slug="acme-production"),
        minimal=lambda c: c.billing.close_periods(),
    ),
    # billing: add-ons
    Case(
        "listAddons",
        lambda c: c.billing.addons.list(lifecycle_state="PUBLISHED", family_slug="extra-seats"),
        minimal=lambda c: c.billing.addons.list(),
    ),
    Case("getAddon", lambda c: c.billing.addons.get("extra-seats-v1")),
    Case(
        "createAddon",
        lambda c: c.billing.addons.create(
            name="Extra seats",
            pricing_type="PAID",
            description="Ten more seats",
            slug="extra-seats-v2",
            family_slug="extra-seats",
            family_id=ID,
            version_name="Winter 2026",
            lifecycle_state="DRAFT",
            is_default=False,
            max_quantity=10,
            increase_billing="TRUE_UP",
        ),
        minimal=lambda c: c.billing.addons.create(name="Extra seats", pricing_type="PAID"),
        required=frozenset({"description"}),
    ),
    Case(
        "updateAddon",
        lambda c: c.billing.addons.update(
            "extra-seats-v1",
            name="Extra seats",
            description="Ten more seats",
            is_default=True,
            version_name="Autumn 2026",
            max_quantity=20,
        ),
        minimal=lambda c: c.billing.addons.update("extra-seats-v1", name="Extra seats"),
        required=frozenset({"description", "isDefault"}),
    ),
    Case("deleteAddon", lambda c: c.billing.addons.delete("extra-seats-v1")),
    Case("publishAddon", lambda c: c.billing.addons.publish("extra-seats-v1")),
    Case("archiveAddon", lambda c: c.billing.addons.archive("extra-seats-v1")),
    Case("unarchiveAddon", lambda c: c.billing.addons.unarchive("extra-seats-v1")),
    Case("listAddonCompatibility", lambda c: c.billing.addons.list_compatibility("extra-seats-v1")),
    Case(
        "setAddonCompatibility",
        lambda c: c.billing.addons.set_compatibility("extra-seats-v1", "growth"),
    ),
    Case(
        "removeAddonCompatibility",
        lambda c: c.billing.addons.remove_compatibility("extra-seats-v1", "growth"),
    ),
    Case("listAddonEntitlements", lambda c: c.billing.addons.list_entitlements("extra-seats-v1")),
    Case(
        "getAddonEntitlement",
        lambda c: c.billing.addons.get_entitlement("extra-seats-v1", "seats"),
    ),
    Case(
        "assignAddonEntitlement",
        lambda c: c.billing.addons.assign_entitlement(
            "extra-seats-v1", "seats", 10, override_behavior="ADD", overage_percent=0
        ),
        minimal=lambda c: c.billing.addons.assign_entitlement("extra-seats-v1", "sso", True),
        required=frozenset({"entitlementSlug", "value"}),
    ),
    Case(
        "updateAddonEntitlement",
        lambda c: c.billing.addons.update_entitlement(
            "extra-seats-v1", "seats", 20, override_behavior="MAX", overage_percent=10
        ),
        minimal=lambda c: c.billing.addons.update_entitlement("extra-seats-v1", "seats", 20),
        forbidden=frozenset({"entitlementSlug"}),
    ),
    Case(
        "unassignAddonEntitlement",
        lambda c: c.billing.addons.unassign_entitlement("extra-seats-v1", "seats"),
    ),
    Case(
        "listAddonPrices",
        lambda c: c.billing.addons.list_prices("extra-seats-v1", status="ACTIVE"),
        minimal=lambda c: c.billing.addons.list_prices("extra-seats-v1"),
    ),
    Case(
        "createAddonPrice",
        lambda c: c.billing.addons.create_price(
            "extra-seats-v1",
            billing_model="FLAT_FEE",
            currency="EUR",
            unit_amount_decimal="1500",
            billing_period="MONTHLY",
            billing_timing="ADVANCE",
            is_default=True,
            display_label="Extra seats",
            display_order=1,
        ),
        minimal=lambda c: c.billing.addons.create_price(
            "extra-seats-v1", billing_model="USAGE_BASED", currency="EUR", unit_amount_decimal="2"
        ),
    ),
    Case(
        "deprecateAddonPrice",
        lambda c: c.billing.addons.deprecate_price("extra-seats-v1", ID),
    ),
    Case("listAddonFamilies", lambda c: c.billing.addons.list_families()),
    Case("getAddonFamily", lambda c: c.billing.addons.get_family("extra-seats")),
    Case(
        "updateAddonFamily",
        lambda c: c.billing.addons.update_family(
            "extra-seats", is_public=True, increase_billing="NEXT_BOUNDARY"
        ),
        minimal=lambda c: c.billing.addons.update_family("extra-seats"),
    ),
    # billing: anonymous checkouts, customer sessions, publishable keys
    Case(
        "listCheckoutSessions",
        lambda c: c.billing.checkout_sessions.list(
            status=["COMPLETED", "ABANDONED"],
            email="ada@acme.com",
            client_reference_id="ref-1",
            limit=10,
        ),
        minimal=lambda c: c.billing.checkout_sessions.list(),
    ),
    Case("getCheckoutSessionAdmin", lambda c: c.billing.checkout_sessions.get(ID)),
    Case(
        "createCustomerSession",
        lambda c: c.billing.customer_sessions.create(
            customer_slug="acme", instance_slug="acme-production", ttl_seconds=900
        ),
        minimal=lambda c: c.billing.customer_sessions.create(customer_slug="acme"),
    ),
    Case("revokeCustomerSession", lambda c: c.billing.customer_sessions.revoke(ID)),
    Case(
        "listPublishableKeys",
        lambda c: c.billing.publishable_keys.list(include_revoked=True),
        minimal=lambda c: c.billing.publishable_keys.list(),
    ),
    Case(
        "createPublishableKey",
        lambda c: c.billing.publishable_keys.create(
            label="Pricing page",
            allowed_origins=["https://acme.com"],
            anonymous_checkout=True,
            turnstile_site_key="0x4AAAAAAA",
            turnstile_secret="0x4BBBBBBB",
        ),
        minimal=lambda c: c.billing.publishable_keys.create(
            label="Pricing page", allowed_origins=[]
        ),
        required=frozenset({"allowedOrigins"}),
    ),
    Case(
        "updatePublishableKey",
        lambda c: c.billing.publishable_keys.update(
            ID,
            label="Pricing page",
            allowed_origins=["https://acme.com"],
            anonymous_checkout=False,
            turnstile_site_key="",
            turnstile_secret="",
        ),
        minimal=lambda c: c.billing.publishable_keys.update(ID),
    ),
    Case("revokePublishableKey", lambda c: c.billing.publishable_keys.revoke(ID)),
    # billing: a customer's payment method and portal
    Case("getCustomerBilling", lambda c: c.billing.customers.get("acme")),
    Case("detachPaymentMethod", lambda c: c.billing.customers.detach_payment_method("acme")),
    Case(
        "createPaymentMethodSession",
        lambda c: c.billing.customers.create_payment_method_session(
            "acme", return_url="https://acme.com/billing", currency="EUR"
        ),
        minimal=lambda c: c.billing.customers.create_payment_method_session(
            "acme", return_url="https://acme.com/billing"
        ),
    ),
    Case(
        "completePaymentMethodSession",
        lambda c: c.billing.customers.complete_payment_method_session("acme", "seti_1"),
    ),
    Case(
        "createPortalSession",
        lambda c: c.billing.customers.create_portal_session(
            "acme", return_url="https://acme.com/billing"
        ),
    ),
    # billing: the accounting handoff
    Case(
        "listHandoff",
        lambda c: c.billing.handoff.list(status="ACKNOWLEDGED", limit=10),
        minimal=lambda c: c.billing.handoff.list(),
    ),
    Case(
        "claimHandoff",
        lambda c: c.billing.handoff.claim(limit=25, lease_seconds=900),
        minimal=lambda c: c.billing.handoff.claim(),
    ),
    Case(
        "ackHandoff",
        lambda c: c.billing.handoff.ack(ID, lease_id=SAMPLE_ID, external_reference="INV-0042"),
        minimal=lambda c: c.billing.handoff.ack(ID),
    ),
    # billing: an instance's add-ons and vouchers
    Case(
        "listInstanceAddons",
        lambda c: c.billing.instance_addons.list("acme-production", include_removed=True),
        minimal=lambda c: c.billing.instance_addons.list("acme-production"),
    ),
    Case(
        "attachInstanceAddon",
        lambda c: c.billing.instance_addons.attach("acme-production", "extra-seats-v1", quantity=2),
        minimal=lambda c: c.billing.instance_addons.attach("acme-production", "extra-seats-v1"),
        required=frozenset({"addonSlug"}),
    ),
    Case(
        "setInstanceAddonQuantity",
        lambda c: c.billing.instance_addons.set_quantity("acme-production", "extra-seats-v1", 3),
    ),
    Case(
        "detachInstanceAddon",
        lambda c: c.billing.instance_addons.detach("acme-production", "extra-seats-v1"),
    ),
    Case(
        "listInstanceVouchers",
        lambda c: c.billing.instance_vouchers.list("acme-production", status="ACTIVE"),
        minimal=lambda c: c.billing.instance_vouchers.list("acme-production"),
    ),
    Case(
        "redeemVoucher",
        lambda c: c.billing.instance_vouchers.redeem("acme-production", "WELCOME-2026"),
    ),
    Case(
        "revokeInstanceVoucher",
        lambda c: c.billing.instance_vouchers.revoke(
            "acme-production", ID, reason="Granted by mistake"
        ),
    ),
    # billing: invoices
    Case(
        "listInvoices",
        lambda c: c.billing.invoices.list(
            instance_slug="acme-production",
            customer_slug="acme",
            status=["MANUAL", "PAID"],
            kind="RENEWAL",
            provider_kind="NOOP",
            overdue=True,
            held=False,
            handoff_status="PENDING",
            issued_from=NOW,
            issued_to=LATER,
            boundary_from=NOW,
            boundary_to=LATER,
            updated_since=NOW,
            limit=10,
        ),
        minimal=lambda c: c.billing.invoices.list(),
    ),
    Case("getInvoice", lambda c: c.billing.invoices.get(ID)),
    Case(
        "exportInvoices",
        lambda c: c.billing.invoices.export(
            format="json",
            granularity="invoice",
            instance_slug="acme-production",
            customer_slug="acme",
            status=["PAID"],
            kind="RENEWAL",
            provider_kind="STRIPE",
            overdue=False,
            held=False,
            handoff_status="ACKNOWLEDGED",
            issued_from=NOW,
            issued_to=LATER,
            boundary_from=NOW,
            boundary_to=LATER,
            updated_since=NOW,
        ),
        minimal=lambda c: c.billing.invoices.export(),
    ),
    Case("voidInvoice", lambda c: c.billing.invoices.void(ID, reason="Duplicate")),
    Case("recomposeInvoice", lambda c: c.billing.invoices.recompose(ID)),
    Case(
        "markInvoicePaid",
        lambda c: c.billing.invoices.mark_paid(
            ID, paid_at=NOW, external_reference="INV-0042", note="Wire 7731"
        ),
        minimal=lambda c: c.billing.invoices.mark_paid(ID),
    ),
    Case("writeOffInvoice", lambda c: c.billing.invoices.write_off(ID, reason="Bankrupt")),
    Case(
        "releaseInvoiceHold",
        lambda c: c.billing.invoices.release_hold(ID, reason="Usage checked by hand"),
    ),
    Case("retryInvoicePush", lambda c: c.billing.invoices.retry_push(ID)),
    Case("syncInvoice", lambda c: c.billing.invoices.sync(ID)),
    Case(
        "listInvoiceLineReports",
        # A ceiling: the fake API answers every page with the same nextAfterSeq.
        lambda c: c.billing.invoices.list_line_reports(ID, SAMPLE_ID, limit=1),
    ),
    # billing: license prices
    Case(
        "listLicensePrices",
        lambda c: c.billing.license_prices.list(
            "growth-v2", status="ACTIVE", billing_model="FLAT_FEE"
        ),
        minimal=lambda c: c.billing.license_prices.list("growth-v2"),
    ),
    Case("getLicensePrice", lambda c: c.billing.license_prices.get("growth-v2", ID)),
    Case(
        "createLicensePrice",
        lambda c: c.billing.license_prices.create(
            "growth-v2",
            billing_model="FLAT_FEE",
            currency="EUR",
            unit_amount_decimal="4900",
            billing_period="ANNUAL",
            billing_timing="ADVANCE",
            is_default=True,
            display_label="Growth, yearly",
            display_order=1,
        ),
        minimal=lambda c: c.billing.license_prices.create(
            "growth-v2",
            billing_model="OVERAGE",
            currency="EUR",
            unit_amount_decimal="2",
            metered_entitlement_slug="api-calls",
        ),
    ),
    Case(
        "updateLicensePrice",
        lambda c: c.billing.license_prices.update(
            "growth-v2",
            ID,
            unit_amount_decimal="5900",
            billing_period="MONTHLY",
            billing_timing="ARREARS",
            metered_entitlement_slug="api-calls",
            is_default=False,
            display_label="Growth",
            display_order=2,
        ),
        minimal=lambda c: c.billing.license_prices.update("growth-v2", ID),
    ),
    Case("deprecateLicensePrice", lambda c: c.billing.license_prices.deprecate("growth-v2", ID)),
    Case(
        "previewLicenseInvoice",
        lambda c: c.billing.license_prices.preview_invoice(
            "growth-v2",
            base_price_id=ID,
            add_ons={"extra-seats-v1": 2},
            sample_usage={"api-calls": "120000"},
            instance_slug="acme-production",
            voucher_code="WELCOME-2026",
        ),
        minimal=lambda c: c.billing.license_prices.preview_invoice("growth-v2"),
    ),
    # billing: what a publishable key and an anonymous checkout's token reach
    Case(
        "getPublicCatalog",
        lambda c: c.billing.public.get_catalog(family_slug="growth", include_addons=False),
        minimal=lambda c: c.billing.public.get_catalog(),
        token="pk_test",
    ),
    Case(
        "createCheckoutSession",
        lambda c: c.billing.public.create_checkout_session(
            turnstile_token="0.turnstile",
            license_slug="growth-v2",
            billing_period="MONTHLY",
            add_ons={"extra-seats-v1": 1},
            email="ada@acme.com",
            return_url="https://acme.com/welcome",
            voucher_code="WELCOME-2026",
            trial=False,
            client_reference_id="ref-1",
            dry_run=True,
        ),
        minimal=lambda c: c.billing.public.create_checkout_session(
            turnstile_token="0.turnstile", price_id=ID
        ),
        required=frozenset({"turnstileToken"}),
        token="pk_test",
    ),
    Case(
        "getCheckoutSession",
        lambda c: c.billing.public.get_checkout_session(ID),
        token="ksc_test",
    ),
    Case(
        "confirmCheckoutSession",
        lambda c: c.billing.public.confirm_checkout_session(ID),
        token="ksc_test",
    ),
    # billing: what a customer session reaches
    Case("getSessionPortal", lambda c: c.billing.session.get_portal(), token="kst_test"),
    Case(
        "listSessionInvoices",
        lambda c: c.billing.session.list_invoices(limit=10),
        minimal=lambda c: c.billing.session.list_invoices(),
        token="kst_test",
    ),
    Case(
        "createSessionCheckout",
        lambda c: c.billing.session.checkout(
            license_price_id=ID,
            add_ons={"extra-seats-v1": 2},
            voucher_code="WELCOME-2026",
            billing_email="billing@acme.com",
            return_url="https://acme.com/billing",
            setup_session_id="seti_1",
            trial=False,
            dry_run=True,
        ),
        minimal=lambda c: c.billing.session.checkout(license_price_id=ID),
        token="kst_test",
    ),
    Case(
        "cancelSessionSubscription",
        lambda c: c.billing.session.cancel(reason="Too expensive"),
        minimal=lambda c: c.billing.session.cancel(),
        token="kst_test",
    ),
    Case(
        "reactivateSessionSubscription",
        lambda c: c.billing.session.reactivate(),
        token="kst_test",
    ),
    Case(
        "setSessionAddonQuantity",
        lambda c: c.billing.session.set_addon_quantity("extra-seats-v1", 0),
        token="kst_test",
    ),
    Case(
        "createSessionPaymentMethodSession",
        lambda c: c.billing.session.create_payment_method_session(
            return_url="https://acme.com/billing", currency="EUR"
        ),
        minimal=lambda c: c.billing.session.create_payment_method_session(
            return_url="https://acme.com/billing"
        ),
        token="kst_test",
    ),
    Case(
        "completeSessionPaymentMethodSession",
        lambda c: c.billing.session.complete_payment_method_session("seti_1"),
        token="kst_test",
    ),
    Case(
        "createSessionPortalSession",
        lambda c: c.billing.session.create_portal_session(return_url="https://acme.com/billing"),
        token="kst_test",
    ),
    Case(
        "validateSessionVoucher",
        lambda c: c.billing.session.validate_voucher("WELCOME-2026", license_price_id=ID),
        minimal=lambda c: c.billing.session.validate_voucher("WELCOME-2026"),
        token="kst_test",
    ),
    Case(
        "redeemSessionVoucher",
        lambda c: c.billing.session.redeem_voucher("WELCOME-2026", dry_run=True),
        minimal=lambda c: c.billing.session.redeem_voucher("WELCOME-2026"),
        token="kst_test",
    ),
    # billing: subscriptions
    Case("getInstanceBilling", lambda c: c.billing.subscriptions.get("acme-production")),
    Case(
        "subscribeInstance",
        lambda c: c.billing.subscriptions.subscribe(
            "acme-production",
            base_price_id=ID,
            add_ons={"extra-seats-v1": 2},
            voucher_code="WELCOME-2026",
            trial_days=14,
            start_at=NOW,
            provider_kind="STRIPE",
            collection_method="CHARGE_AUTOMATICALLY",
            days_until_due=30,
        ),
        minimal=lambda c: c.billing.subscriptions.subscribe("acme-production", base_price_id=ID),
    ),
    Case(
        "updateInstanceBilling",
        lambda c: c.billing.subscriptions.update(
            "acme-production",
            provider_kind="STRIPE",
            collection_method="CHARGE_AUTOMATICALLY",
            days_until_due=14,
        ),
        minimal=lambda c: c.billing.subscriptions.update("acme-production"),
    ),
    Case(
        "updateInstanceBilling",
        # None is sent as null: back to the organization's default.
        lambda c: c.billing.subscriptions.update(
            "acme-production", collection_method=None, days_until_due=None
        ),
        required=frozenset({"collectionMethod", "daysUntilDue"}),
        name="updateInstanceBilling-defaults",
    ),
    Case(
        "cancelSubscription",
        lambda c: c.billing.subscriptions.cancel(
            "acme-production", mode="IMMEDIATE", reason="Churned"
        ),
        minimal=lambda c: c.billing.subscriptions.cancel("acme-production"),
    ),
    Case("reactivateSubscription", lambda c: c.billing.subscriptions.reactivate("acme-production")),
    Case(
        "schedulePlanChange",
        lambda c: c.billing.subscriptions.schedule_plan_change("acme-production", ID),
        required=frozenset({"licensePriceId"}),
    ),
    Case(
        "cancelPlanChange",
        lambda c: c.billing.subscriptions.cancel_plan_change("acme-production"),
    ),
    Case(
        "getUpcomingInvoice",
        lambda c: c.billing.subscriptions.get_upcoming_invoice("acme-production"),
    ),
    Case(
        "listInstanceInvoices",
        lambda c: c.billing.subscriptions.list_invoices(
            "acme-production",
            customer_slug="acme",
            status=["PUSHED"],
            kind="ACTIVATION",
            provider_kind="STRIPE",
            overdue=True,
            held=False,
            handoff_status="NOT_REQUIRED",
            issued_from=NOW,
            issued_to=LATER,
            boundary_from=NOW,
            boundary_to=LATER,
            updated_since=NOW,
            limit=5,
        ),
        minimal=lambda c: c.billing.subscriptions.list_invoices("acme-production"),
    ),
    # billing: vouchers
    Case(
        "listVouchers",
        lambda c: c.billing.vouchers.list(
            status="ACTIVE", voucher_type="PRICE", restricted_customer_slug="acme"
        ),
        minimal=lambda c: c.billing.vouchers.list(),
    ),
    Case("getVoucher", lambda c: c.billing.vouchers.get(ID)),
    Case(
        "createVoucher",
        lambda c: c.billing.vouchers.create(**VOUCHER),
        minimal=lambda c: c.billing.vouchers.create(
            name="Welcome", voucher_type="PRICE", duration="ONE_TIME"
        ),
    ),
    Case(
        "updateVoucher",
        lambda c: c.billing.vouchers.update(ID, **VOUCHER),
        minimal=lambda c: c.billing.vouchers.update(
            ID, name="Welcome", voucher_type="PRICE", duration="FOREVER"
        ),
    ),
    Case("deleteVoucher", lambda c: c.billing.vouchers.delete(ID)),
    Case("publishVoucher", lambda c: c.billing.vouchers.publish(ID)),
    Case("archiveVoucher", lambda c: c.billing.vouchers.archive(ID)),
    Case(
        "listVoucherRedemptions",
        lambda c: c.billing.vouchers.list_redemptions(ID, limit=10),
        minimal=lambda c: c.billing.vouchers.list_redemptions(ID),
    ),
    Case(
        "lookupVoucher",
        lambda c: c.billing.vouchers.lookup("WELCOME-2026"),
        required=frozenset({"code"}),
    ),
    Case(
        "validateVoucher",
        lambda c: c.billing.vouchers.validate(
            "WELCOME-2026", instance_slug="acme-production", license_price_id=ID
        ),
        minimal=lambda c: c.billing.vouchers.validate("WELCOME-2026"),
    ),
    # platform
    Case("get-platform-me", lambda p: p.me(), surface="platform"),
    Case(
        "register-connector",
        lambda p: p.connectors.register(
            name=CONNECTOR,
            version="1.0.0",
            settings_schema={"type": "object", "properties": {"apiKey": {"writeOnly": True}}},
            entitlement_slug="crm",
        ),
        minimal=lambda p: p.connectors.register(name=CONNECTOR, version="1.0.0"),
        required=frozenset({"settings_schema"}),
        surface="platform",
    ),
    Case(
        "ensure-organization",
        lambda p: p.organizations.ensure(external_id="org_2abcDEF", name="Acme"),
        minimal=lambda p: p.organizations.ensure(external_id="org_2abcDEF"),
        surface="platform",
    ),
    Case("get-organization", lambda p: p.organizations.get(ORG_ID), surface="platform"),
    Case("delete-organization", lambda p: p.organizations.delete(ORG_ID), surface="platform"),
    Case(
        "delete-membership",
        lambda p: p.organizations.delete_membership(ORG_ID, USER_ID),
        surface="platform",
    ),
    Case(
        "mint-organization-token",
        lambda p: p.tokens.mint(
            ORG_ID, name="billing-sync", scopes=["write:instances"], ttl=timedelta(hours=24)
        ),
        minimal=lambda p: p.tokens.mint(ORG_ID, name="billing-sync"),
        surface="platform",
    ),
    Case("list-organization-tokens", lambda p: p.tokens.list(ORG_ID), surface="platform"),
    Case(
        "revoke-organization-token",
        lambda p: p.tokens.revoke(ORG_ID, "system-kaiten-2c8293"),
        surface="platform",
    ),
    Case("delete-user", lambda p: p.users.delete(USER_ID), surface="platform"),
    Case(
        "platform-close-billing-periods",
        lambda p: p.billing.close_periods(ORG_ID, instance_slug="acme-production"),
        minimal=lambda p: p.billing.close_periods(ORG_ID),
        surface="platform",
    ),
]


def _invocations() -> list[Any]:
    params = []
    for case in CASES:
        label = case.name or case.operation_id
        params.append(pytest.param(case, case.call, id=label))
        if case.minimal is not None:
            params.append(pytest.param(case, case.minimal, id=f"{label}-minimal"))
    return params


def check(case: Case, recorder: Recorder) -> None:
    assert recorder, "the method sent no request"
    for request in recorder:
        operation = find_operation(case.surface, request.method, request.url.path)
        assert operation.operation_id == case.operation_id
        assert set(request.url.params.keys()) <= operation.query_parameters
        header = credential_header(case.surface, operation)
        if header == "Authorization":
            assert request.headers["authorization"].startswith("Bearer ")
        else:
            assert "authorization" not in request.headers, "the API refuses this credential there"
            assert request.headers[header]

        schema = operation.request_schema
        if schema is None:
            assert not request.content, f"{case.operation_id} takes no body"
            continue
        payload = body(request)
        assert write_errors(case.surface, schema, payload) == []
        assert not case.forbidden & payload.keys(), f"sent {case.forbidden & payload.keys()}"
        assert case.required <= payload.keys(), f"missing {case.required - payload.keys()}"


def credential_header(surface: str, operation: Operation) -> str:
    """The header the operation's security scheme carries the credential in."""
    contract = document(surface)
    requirements = operation.definition.get("security", contract.get("security")) or [{}]
    (scheme,) = {name for requirement in requirements for name in requirement}
    definition = contract["components"]["securitySchemes"][scheme]
    return str(definition["name"]) if definition["type"] == "apiKey" else "Authorization"


def options(case: Case) -> dict[str, Any]:
    return {"token": case.token} if case.token else {}


@pytest.mark.parametrize(("case", "call"), _invocations())
def test_sync_client_speaks_the_contract(
    case: Case,
    call: Callable[[Any], Any],
    make_client: Callable[..., Any],
    make_platform_client: Callable[..., Any],
) -> None:
    factory = make_platform_client if case.surface == "platform" else make_client
    client, recorder = factory(contract_api(case.surface), **options(case))
    call(client)
    check(case, recorder)


@pytest.mark.parametrize(("case", "call"), _invocations())
def test_async_client_speaks_the_contract(
    case: Case,
    call: Callable[[Any], Any],
    make_async_client: Callable[..., Any],
    make_async_platform_client: Callable[..., Any],
) -> None:
    factory = make_async_platform_client if case.surface == "platform" else make_async_client

    async def scenario() -> Recorder:
        client, recorder = factory(contract_api(case.surface), **options(case))
        async with client:
            await call(client)
        return recorder

    check(case, asyncio.run(scenario()))


def test_every_mapped_operation_has_a_contract_case() -> None:
    from contract import coverage

    covered = {case.operation_id for case in CASES}
    for surface in ("core", "platform"):
        mapped = set(coverage()[surface]["operations"])
        assert mapped - covered == set(), f"{surface} operations without a contract case"
