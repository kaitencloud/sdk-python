# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Models are lenient where the API grows, and give the exact wire shape back."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

import pytest
from contract import ROOT, document, sample

import kaitencloud.types as types
from kaitencloud import KaitenModel
from kaitencloud.types import (
    BasicVariant,
    Customer,
    EntitlementUsage,
    FeatureFlag,
    Instance,
    NumberEntitlementValue,
    RolloutPercentageTargeting,
)

sys.path.insert(0, str(ROOT / "scripts"))
from generate_models import CLASS_NAMES

PLATFORM_ONLY = {"Organization", "PlatformCredential"}
SCHEMA_NAMES = {python: schema for schema, python in CLASS_NAMES.items()}
MODELS = sorted(
    name
    for name in types.__all__
    if isinstance(getattr(types, name), type) and issubclass(getattr(types, name), KaitenModel)
)

CUSTOMER = {
    "id": "c1",
    "name": "Acme",
    "externalCustomerId": None,
    "createdAt": "2026-09-14T12:00:00Z",
    "updatedAt": "2026-09-14T12:00:00Z",
    "createdBy": {"id": "u1", "name": "Ada"},
    "updatedBy": {"id": "u1"},
}


@pytest.mark.parametrize("name", MODELS)
def test_every_model_round_trips_a_payload_shaped_like_its_schema(name: str) -> None:
    model: type[KaitenModel] = getattr(types, name)
    surface = "platform" if name in PLATFORM_ONLY else "core"
    schema = {"$ref": f"#/components/schemas/{SCHEMA_NAMES.get(name, name)}"}
    assert SCHEMA_NAMES.get(name, name) in document(surface)["components"]["schemas"]

    full: dict[str, Any] = sample(schema, surface)
    assert model.model_validate(full).to_dict() == full
    model.model_validate(sample(schema, surface, full=False))


def test_attributes_are_snake_case_and_to_dict_gives_wire_names_back() -> None:
    customer = Customer.model_validate(CUSTOMER)
    assert customer.external_customer_id is None
    assert customer.created_at == datetime(2026, 9, 14, 12, tzinfo=timezone.utc)
    assert customer.created_by.name == "Ada"
    assert customer.to_dict() == CUSTOMER
    assert '"createdAt":"2026-09-14T12:00:00Z"' in customer.to_json()


def test_a_model_can_be_built_from_attribute_names() -> None:
    customer = Customer(
        id="c1",
        name="Acme",
        created_at=datetime(2026, 9, 14, 12, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 14, 12, tzinfo=timezone.utc),
        created_by={"id": "u1"},
        updated_by={"id": "u1"},
    )
    assert customer.to_dict()["createdAt"] == "2026-09-14T12:00:00Z"


def test_an_enum_value_newer_than_the_sdk_parses_as_a_string() -> None:
    instance = Instance.model_validate(
        {
            **sample({"$ref": "#/components/schemas/Instance"}, "core"),
            "status": "HIBERNATING",
        }
    )
    assert instance.status == "HIBERNATING"


def test_a_field_newer_than_the_sdk_is_kept_rather_than_refused() -> None:
    customer = Customer.model_validate({**CUSTOMER, "healthScore": 92})
    assert customer.model_extra == {"healthScore": 92}
    assert customer.to_dict()["healthScore"] == 92


def test_discriminated_values_parse_into_their_own_class() -> None:
    usage = EntitlementUsage.model_validate(
        {
            "entitlementId": "e1",
            "entitlementSlug": "seats",
            "licenseId": "l1",
            "licenseSlug": "growth",
            "value": {"type": "number", "value": 7, "event_count": 3},
            "limit": {"type": "number", "value": 10},
        }
    )
    assert isinstance(usage.value, NumberEntitlementValue)
    assert (usage.value.value, usage.value.event_count) == (7, 3)
    assert isinstance(usage.limit, NumberEntitlementValue)
    assert usage.current_period_start is None


def test_a_flag_parses_its_default_variant_and_rules_by_type() -> None:
    flag = FeatureFlag.model_validate(
        {
            **sample({"$ref": "#/components/schemas/FeatureFlag"}, "core"),
            "default_variant": {"type": "basic", "value": "off"},
            "targetings": [
                {
                    "type": "rollout_percentage",
                    "name": "Rollout",
                    "rule": "true",
                    "distribution": {"on": 1},
                }
            ],
        }
    )
    assert isinstance(flag.default_variant, BasicVariant)
    assert flag.targetings is not None
    assert isinstance(flag.targetings[0], RolloutPercentageTargeting)


def test_types_exports_the_parameter_shapes_too() -> None:
    assert {"IntegrationParam", "VariantParam", "TargetingParam"} <= set(types.__all__)
