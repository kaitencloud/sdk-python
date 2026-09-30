# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""What the contract table cannot see: value encoding, escaping, defaults and early refusals."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from contract import sample
from helpers import ORG_ID, body, respond

from kaitencloud.types import ManifestFlag, NumberEntitlementValue

CUSTOMER = {
    "id": "c1",
    "name": "Acme",
    "slug": "acme",
    "createdAt": "2026-09-14T12:00:00Z",
    "updatedAt": "2026-09-14T12:00:00Z",
    "createdBy": {"id": "u1"},
    "updatedBy": {"id": "u1"},
}
TOKEN = {
    "name": "billing-sync",
    "slug": "system-kaiten-2c8293",
    "token": "ksh_plaintext",
    "scopes": ["write:instances"],
    "createdAt": "2026-09-14T12:00:00Z",
    "createdBy": {"id": "u1"},
}
INSTANCE_WRITE = {
    "name": "Acme production",
    "customer_id": "c1",
    "license_id": "l1",
    "start_license_date": datetime(2026, 9, 14, tzinfo=timezone.utc),
    "end_license_date": datetime(2027, 9, 14, tzinfo=timezone.utc),
}
INSTANCE = sample({"$ref": "#/components/schemas/Instance"}, "core")
FAMILY = sample({"$ref": "#/components/schemas/LicenseFamilyView"}, "core")
USAGE = sample({"$ref": "#/components/schemas/EntitlementUsage"}, "core")


def test_a_slug_is_escaped_into_a_single_path_segment(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(200, CUSTOMER))
    client.customers.get("acme/../admin")
    assert recorder.only.url.raw_path == b"/api/customers/acme%2F..%2Fadmin"


@pytest.mark.parametrize("slug", ["", "   "])
def test_an_empty_slug_is_refused_before_anything_is_sent(
    make_client: Callable[..., Any], slug: str
) -> None:
    client, recorder = make_client(respond(204))
    with pytest.raises(ValueError, match="non-empty"):
        client.customers.delete(slug)
    assert not recorder


@pytest.mark.parametrize(
    ("value", "wire"),
    [
        (True, {"type": "boolean", "value": True}),
        (False, {"type": "boolean", "value": False}),
        (50, {"type": "number", "value": 50}),
        (2.5, {"type": "number", "value": 2.5}),
        (-1, {"type": "number", "value": -1}),
        ({"theme": "dark"}, {"type": "object", "value": {"theme": "dark"}}),
    ],
)
def test_an_entitlement_value_is_wrapped_according_to_its_type(
    make_client: Callable[..., Any], value: Any, wire: dict[str, Any]
) -> None:
    client, recorder = make_client(respond(204))
    client.licenses.update_entitlement("growth", "seats", value)
    assert body(recorder.only) == {"value": wire}


def test_an_entitlement_value_model_is_sent_without_its_server_fields(
    make_client: Callable[..., Any],
) -> None:
    client, recorder = make_client(respond(204))
    value = NumberEntitlementValue(type="number", value=10, event_count=3)
    client.licenses.associate_entitlement("growth", "seats", value, overage_percent=0)
    assert body(recorder.only) == {
        "entitlementSlug": "seats",
        "value": {"type": "number", "value": 10.0},
        "limitCapExceededOveragePercent": 0,
    }


def test_an_entitlement_value_of_another_type_is_refused(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(204))
    with pytest.raises(TypeError, match="entitlement value"):
        client.licenses.update_entitlement("growth", "seats", "fifty")  # type: ignore[arg-type]
    assert not recorder


def test_datetimes_are_sent_as_utc_rfc3339(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(201, INSTANCE))
    paris = timezone(timedelta(hours=2))

    client.instances.create(
        **{
            **INSTANCE_WRITE,
            "start_license_date": datetime(2026, 9, 14, 14, 0, tzinfo=paris),
            "end_license_date": "2027-09-14T00:00:00Z",
        }
    )

    payload = body(recorder.only)
    assert payload["startLicenseDate"] == "2026-09-14T12:00:00Z"
    assert payload["endLicenseDate"] == "2027-09-14T00:00:00Z"


def test_a_naive_datetime_is_refused_rather_than_guessed(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(204))
    with pytest.raises(ValueError, match="timezone"):
        client.instances.update(
            "acme-production", **{**INSTANCE_WRITE, "start_license_date": datetime(2026, 9, 14)}
        )
    assert not recorder


def test_an_instance_update_leaves_out_what_it_keeps(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(204))
    client.instances.update("acme-production", **INSTANCE_WRITE)
    assert body(recorder.only) == {
        "name": "Acme production",
        "description": "",
        "customerId": "c1",
        "licenseId": "l1",
        "startLicenseDate": "2026-09-14T00:00:00Z",
        "endLicenseDate": "2027-09-14T00:00:00Z",
    }


def test_an_instance_update_with_a_slug_renames_it(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(204))
    client.instances.update("acme-production", **INSTANCE_WRITE, slug="acme-prod")
    assert body(recorder.only)["slug"] == "acme-prod"


def test_a_required_nullable_description_is_sent_as_null(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(204))
    client.entitlements.update("seats", name="Seats")
    assert body(recorder.only) == {"name": "Seats", "description": None}


def test_a_token_without_scopes_inherits_them_by_sending_null(
    make_client: Callable[..., Any],
) -> None:
    client, recorder = make_client(respond(201, TOKEN))
    client.service_accounts.create_token("billing-sync", name="ci")
    assert body(recorder.only) == {"name": "ci", "scopes": None}


def test_a_feature_flag_needs_only_the_essentials(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(204))

    client.feature_flags.update(
        "new-checkout",
        name="New checkout",
        type="boolean",
        variants=[{"name": "on", "value": True}, {"name": "off", "value": False}],
        default_variant="off",
    )

    assert body(recorder.only) == {
        "name": "New checkout",
        "type": "boolean",
        "variants": [
            {"name": "on", "description": "", "value": True},
            {"name": "off", "description": "", "value": False},
        ],
        "default_variant": {"type": "basic", "value": "off"},
        "targetings": [],
        "enabled": True,
        "description": None,
        "metadata": {},
        "event_name": "",
    }


def test_usage_defaults_to_append(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(200, USAGE))
    client.instances.report_usage("acme-production", "seats", 3)
    assert body(recorder.only) == {"value": {"type": "number", "value": 3}, "behavior": "append"}


def test_usage_must_be_a_number(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(204))
    with pytest.raises(TypeError, match="number"):
        client.instances.report_usage("acme-production", "seats", True)
    assert not recorder


def test_audit_trail_filters_travel_as_query_parameters(make_client: Callable[..., Any]) -> None:
    client, recorder = make_client(respond(200, {"items": [], "hasMore": False}))
    client.instances.list_audit_trails(
        "acme-production",
        event_name="INSTANCE_STATUS_CHANGED",
        after=datetime(2026, 9, 1, tzinfo=timezone.utc),
        before="2026-09-14T00:00:00Z",
        limit=20,
    )
    assert dict(recorder.only.url.params) == {
        "event_name": "INSTANCE_STATUS_CHANGED",
        "after": "2026-09-01T00:00:00Z",
        "before": "2026-09-14T00:00:00Z",
        "limit": "20",
    }


def test_a_family_resolves_to_its_current_version_when_asked_nothing(
    make_client: Callable[..., Any],
) -> None:
    client, recorder = make_client(respond(200, FAMILY))
    client.license_families.get("growth")
    assert recorder.only.url.path.endswith("/license-families/growth")
    assert not recorder.only.url.params  # no version pinned, no extra representation


def test_a_pinned_version_and_the_history_travel_as_query_parameters(
    make_client: Callable[..., Any],
) -> None:
    client, recorder = make_client(respond(200, FAMILY))
    client.license_families.get("growth", version=2, include_versions=True)
    assert dict(recorder.only.url.params) == {"version": "2", "include": "versions"}


def test_a_new_version_names_its_family_and_starts_as_a_draft_when_asked(
    make_client: Callable[..., Any],
) -> None:
    license = sample({"$ref": "#/components/schemas/License"}, "core")
    client, recorder = make_client(respond(201, license))
    client.licenses.create(
        name="Growth", type="PAID", family_slug="growth", lifecycle_state="DRAFT"
    )
    sent = body(recorder.only)
    assert sent["familySlug"] == "growth"
    assert sent["lifecycleState"] == "DRAFT"
    assert "familyId" not in sent  # unset, rather than sent empty


def test_a_new_license_opens_a_family_by_naming_none(make_client: Callable[..., Any]) -> None:
    license = sample({"$ref": "#/components/schemas/License"}, "core")
    client, recorder = make_client(respond(201, license))
    client.licenses.create(name="Growth", type="PAID")
    assert not {"familySlug", "familyId", "lifecycleState"} & body(recorder.only).keys()


@pytest.mark.parametrize("transition", ["publish", "archive", "unarchive"])
def test_a_lifecycle_transition_is_a_bodiless_post_that_returns_the_version(
    make_client: Callable[..., Any], transition: str
) -> None:
    license = sample({"$ref": "#/components/schemas/License"}, "core")
    client, recorder = make_client(respond(200, license))
    moved = getattr(client.licenses, transition)("growth-v2")
    assert moved.id == license["id"]
    assert recorder.only.method == "POST"
    assert recorder.only.url.path.endswith(f"/licenses/growth-v2/{transition}")
    assert not recorder.only.content


@pytest.mark.parametrize("payload", [None, "null", []], ids=["empty", "null", "array"])
def test_an_unpaginated_list_reads_null_as_empty(
    make_client: Callable[..., Any], payload: Any
) -> None:
    client, _ = make_client(respond(200, payload))
    assert client.instances.list_usage("acme-production") == []


def test_the_manifest_is_its_list_of_flags(make_client: Callable[..., Any]) -> None:
    flag = {"key": "new-checkout", "type": "boolean", "defaultValue": False}
    client, _ = make_client(respond(200, {"flags": [flag]}))
    assert client.feature_flags.manifest() == [ManifestFlag.model_validate(flag)]


def test_a_platform_id_must_be_a_uuid(make_platform_client: Callable[..., Any]) -> None:
    client, recorder = make_platform_client(respond(201, TOKEN))
    with pytest.raises(ValueError, match="organization_id"):
        client.tokens.mint("acme", name="billing-sync")
    assert not recorder


@pytest.mark.parametrize(
    ("ttl", "wire"),
    [
        (timedelta(minutes=15), "900s"),
        (timedelta(hours=24), "86400s"),
        (timedelta(milliseconds=1500), "1.5s"),
        ("15m", "15m"),
    ],
)
def test_a_token_ttl_is_sent_as_a_go_duration(
    make_platform_client: Callable[..., Any], ttl: timedelta | str, wire: str
) -> None:
    client, recorder = make_platform_client(respond(201, TOKEN))
    minted = client.tokens.mint(ORG_ID, name="billing-sync", ttl=ttl)
    assert body(recorder.only) == {"name": "billing-sync", "ttl": wire}
    assert (minted.token, minted.slug) == ("ksh_plaintext", "system-kaiten-2c8293")


def test_a_token_ttl_must_be_positive(make_platform_client: Callable[..., Any]) -> None:
    client, recorder = make_platform_client(respond(201, TOKEN))
    with pytest.raises(ValueError, match="positive"):
        client.tokens.mint(ORG_ID, name="billing-sync", ttl=timedelta(0))
    assert not recorder


def test_registering_a_connector_sends_an_empty_schema_by_default(
    make_platform_client: Callable[..., Any],
) -> None:
    connector = {
        "name": "kaiten.integration.crm.acme",
        "version": "1.0.0",
        "settings_schema": {},
        "created_at": "2026-09-14T12:00:00Z",
        "updated_at": "2026-09-14T12:00:00Z",
    }
    client, recorder = make_platform_client(respond(200, connector))
    client.connectors.register(name="kaiten.integration.crm.acme", version="1.0.0")
    assert body(recorder.only) == {
        "name": "kaiten.integration.crm.acme",
        "version": "1.0.0",
        "settings_schema": {},
    }
