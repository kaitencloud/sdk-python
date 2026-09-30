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
  create refuses.

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
from contract import contract_api, find_operation, write_errors
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
        ),
        minimal=lambda c: c.customers.create(name="Acme"),
    ),
    Case(
        "update-customer",
        lambda c: c.customers.update(
            "acme", name="Acme Corp", external_customer_id="crm-42", domain="acme.com"
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
        forbidden=frozenset({"slug"}),
    ),
    Case("delete-feature-flag", lambda c: c.feature_flags.delete("new-checkout")),
    Case("get-openfeature-manifest", lambda c: c.feature_flags.manifest()),
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
    Case("list-metadata-fields", lambda c: c.metadata_fields.list("INSTANCE")),
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
        assert request.headers["authorization"].startswith("Bearer ")

        schema = operation.request_schema
        if schema is None:
            assert not request.content, f"{case.operation_id} takes no body"
            continue
        payload = body(request)
        assert write_errors(case.surface, schema, payload) == []
        assert not case.forbidden & payload.keys(), f"sent {case.forbidden & payload.keys()}"
        assert case.required <= payload.keys(), f"missing {case.required - payload.keys()}"


@pytest.mark.parametrize(("case", "call"), _invocations())
def test_sync_client_speaks_the_contract(
    case: Case,
    call: Callable[[Any], Any],
    make_client: Callable[..., Any],
    make_platform_client: Callable[..., Any],
) -> None:
    factory = make_platform_client if case.surface == "platform" else make_client
    client, recorder = factory(contract_api(case.surface))
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
        client, recorder = factory(contract_api(case.surface))
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
