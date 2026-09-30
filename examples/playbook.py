#!/usr/bin/env python3
# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""A scripted walk through a Kaiten deployment, one step at a time.

The playbook builds a small but complete world -- a catalog, a license, a customer, a release,
an instance, a feature flag -- meters usage against it until the license refuses a report, and
can then delete everything it made.

Every resource it creates is named after the run (``playbook-<run>-...``), so it never touches
anything else, and everything it creates is written to a state file, so you can stop after any
step and pick up later::

    uv run python examples/playbook.py --list          # the steps, in order
    uv run python examples/playbook.py                 # run them all
    uv run python examples/playbook.py --pause         # stop before each one
    uv run python examples/playbook.py --from usage    # resume at a step
    uv run python examples/playbook.py catalog license # run only these
    uv run python examples/playbook.py cleanup         # delete what this run created

It reads the same environment as the SDK -- ``KAITEN_BASE_URL`` and ``KAITEN_AUTH_TOKEN``, plus
``KAITEN_PLATFORM_BASE_URL`` and ``KAITEN_PLATFORM_TOKEN`` for the platform step -- or takes
``--base-url`` and ``--token``.

It writes real data into the organization your token belongs to. Point it at a development
deployment, and run ``cleanup`` when you are done.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import logging
import os
import random
import string
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from kaitencloud import (
    UNLIMITED,
    APIStatusError,
    AuthenticationError,
    ConflictError,
    CredentialError,
    KaitenClient,
    KaitenPlatformClient,
    NotFoundError,
    PermissionDeniedError,
    ThresholdExceededError,
    targeting,
)
from kaitencloud import usage as enforcement
from kaitencloud.types import EntitlementUsage
from kaitencloud.types import NumberEntitlementValue as Number
from kaitencloud.webhooks import (
    InstanceEntitlementCapExceededEvent,
    WebhookVerificationError,
    verify_webhook,
)

if TYPE_CHECKING:  # the OpenFeature SDK is the flag client; see the flags step
    from openfeature.client import OpenFeatureClient

T = TypeVar("T")

STATE_FILE = Path(".kaiten-playbook.json")
ADAPTER = "playbook-crm"


# --------------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------------

COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ


def paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def heading(text: str) -> None:
    print(paint(f"\n{text}", "1;36"))


def call(code: str) -> None:
    """Show the SDK call a step is about to make."""
    print("   " + paint(code, "2"))


def note(text: str) -> None:
    print(f"   {text}")


def done(text: str) -> None:
    print("   " + paint("+ ", "32") + text)


def warn(text: str) -> None:
    print("   " + paint("! ", "33") + text)


# --------------------------------------------------------------------------------------------
# State: what this run created, so a later step -- or a later day -- can pick it up
# --------------------------------------------------------------------------------------------


@dataclass
class State:
    path: Path
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True) + "\n", "utf-8")

    def clear(self) -> None:
        self.data = {}
        self.path.unlink(missing_ok=True)


@dataclass
class Playbook:
    """What every step is handed: the clients, and the memory of what the run created."""

    client: KaitenClient
    state: State
    platform: KaitenPlatformClient | None = None
    platform_org: str | None = None
    client_factory: Callable[[str], KaitenClient] | None = None
    token: str | None = None
    """The credential the OpenFeature provider sends, since it is not this SDK's client."""

    @property
    def run(self) -> str:
        """The id of this run, minted once and kept in the state file."""
        run: str | None = self.state.get("run")
        if not run:
            run = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
            self.state.set("run", run)
        return run

    def slug(self, name: str) -> str:
        return f"playbook-{self.run}-{name}"

    def title(self, name: str) -> str:
        return f"Playbook {self.run}: {name}"

    def track(self, kind: str, identifier: str) -> None:
        """Remember a created resource, so cleanup deletes it and only it."""
        created: dict[str, list[str]] = self.state.get("created", {})
        created.setdefault(kind, [])
        if identifier not in created[kind]:
            created[kind].append(identifier)
        self.state.set("created", created)

    def created(self, kind: str) -> list[str]:
        created: dict[str, list[str]] = self.state.get("created", {})
        return list(created.get(kind, []))

    def new_client(self, token: str) -> KaitenClient:
        """A second client, for trying a credential this run minted."""
        if self.client_factory is not None:
            return self.client_factory(token)
        return KaitenClient(base_url=self.client.base_url, token=token, max_retries=0)


class PlaybookError(RuntimeError):
    """The deployment answered something the playbook cannot continue from."""


def required(value: T | None, what: str) -> T:
    if value is None:
        raise PlaybookError(f"the API did not return {what}")
    return value


def ensure(what: str, create: Callable[[], T]) -> T | None:
    """Create something, and shrug when this run already did."""
    try:
        created = create()
    except ConflictError:
        note(f"{what} is already there")
        return None
    done(f"created {what}")
    return created


def amount(usage: EntitlementUsage) -> float | None:
    """The numeric usage in a reading, when there is one."""
    return usage.value.value if isinstance(usage.value, Number) else None


# --------------------------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    name: str
    title: str
    run: Callable[[Playbook], None]


STEPS: list[Step] = []


def step(
    name: str, title: str
) -> Callable[[Callable[[Playbook], None]], Callable[[Playbook], None]]:
    def register(function: Callable[[Playbook], None]) -> Callable[[Playbook], None]:
        STEPS.append(Step(name, title, function))
        return function

    return register


@step("connect", "Read every collection, and see what the credential may do")
def connect(book: Playbook) -> None:
    client = book.client
    note(f"base URL {client.base_url}")
    call("client.<resource>.list()  # each one walks every page")

    readers: dict[str, Callable[[], Sequence[object]]] = {
        "customers": client.customers.list,
        "instances": client.instances.list,
        "license families": client.license_families.list,
        "licenses": client.licenses.list,
        "entitlements": client.entitlements.list,
        "entitlement groups": client.entitlement_groups.list,
        "feature flags": client.feature_flags.list,
        "deployment zones": client.deployment_zones.list,
        "releases": client.releases.list,
        "components": client.components.list,
        "service accounts": client.service_accounts.list,
        "connectors": client.connectors.list,
        "metadata fields (instances)": lambda: client.metadata_fields.list("INSTANCE"),
    }
    for label, read in readers.items():
        try:
            note(f"{len(read()):>5}  {label}")
        except PermissionDeniedError:
            warn(f"{'--':>5}  {label}: this credential has no scope for it")
    done("the API answers, and the run can start")


@step("catalog", "An entitlement group, and the entitlements it holds")
def catalog(book: Playbook) -> None:
    client = book.client
    group, seats, calls, sso = (
        book.slug("quotas"),
        book.slug("seats"),
        book.slug("api-calls"),
        book.slug("sso"),
    )

    call("client.entitlement_groups.create(name=..., slug=..., description=...)")
    ensure(
        f"entitlement group {group}",
        lambda: client.entitlement_groups.create(
            name=book.title("Quotas"), slug=group, description="What the playbook meters"
        ),
    )
    book.track("entitlement_groups", group)

    call('client.entitlements.create(name=..., type="NUMBER", unit_singular="seat", ...)')
    ensure(
        f"entitlement {seats}",
        lambda: client.entitlements.create(
            name=book.title("Seats"),
            slug=seats,
            type="NUMBER",
            description="Named users",
            aggregation_method="SUM",
            unit_singular="seat",
            unit_plural="seats",
            user_facing=True,
            display_order=1,
            warning_threshold_percent=80,
            group_slugs=[group],
        ),
    )
    book.track("entitlements", seats)

    call('client.entitlements.create(..., reset_period="MONTH", reset_anchor="CALENDAR")')
    ensure(
        f"entitlement {calls}",
        lambda: client.entitlements.create(
            name=book.title("API calls"),
            slug=calls,
            type="NUMBER",
            description="Calls, counted per calendar month",
            aggregation_method="SUM",
            reset_period="MONTH",
            reset_anchor="CALENDAR",
            unit_singular="call",
            unit_plural="calls",
            group_slugs=[group],
        ),
    )
    book.track("entitlements", calls)

    call('client.entitlements.create(..., type="BOOLEAN")')
    ensure(
        f"entitlement {sso}",
        lambda: client.entitlements.create(
            name=book.title("Single sign-on"), slug=sso, type="BOOLEAN", description="SSO"
        ),
    )
    book.track("entitlements", sso)

    call(f'client.entitlements.get("{seats}")')
    entitlement = client.entitlements.get(seats)
    note(
        f"{entitlement.name}: {entitlement.type}, folded with {entitlement.aggregation_method}, "
        f"warning at {entitlement.warning_threshold_percent}%"
    )

    call(f'client.entitlement_groups.add_entitlement("{group}", "{sso}")')
    client.entitlement_groups.add_entitlement(group, sso)
    call(f'client.entitlement_groups.remove_entitlement("{group}", "{sso}")')
    client.entitlement_groups.remove_entitlement(group, sso)
    done("the group took the entitlement, and gave it back")

    note("update() replaces: everything to keep has to be sent again")
    call("client.entitlements.update(slug, ..., display_order=2, warning_threshold_percent=90)")
    client.entitlements.update(
        seats,
        name=book.title("Seats"),
        type="NUMBER",
        description="Named users",
        aggregation_method="SUM",
        unit_singular="seat",
        unit_plural="seats",
        user_facing=True,
        display_order=2,
        warning_threshold_percent=90,
        group_slugs=[group],
    )
    done("seats now warn at 90% of the cap")


@step("license", "A license, the values it grants, and a second version of it")
def license_step(book: Playbook) -> None:
    client = book.client
    slug, seats, calls, sso = (
        book.slug("growth"),
        book.slug("seats"),
        book.slug("api-calls"),
        book.slug("sso"),
    )

    call('client.licenses.create(name=..., slug=..., type="PAID", description=...)')
    ensure(
        f"license {slug}",
        lambda: client.licenses.create(
            name=book.title("Growth"),
            slug=slug,
            type="PAID",
            description="The plan the playbook meters against",
        ),
    )
    book.track("licenses", slug)

    note("5 seats with a 20% allowance, so the usage step can reach the refusal")
    call("client.licenses.associate_entitlement(license, entitlement, 5, overage_percent=20)")
    ensure(
        f"grant of {seats}",
        lambda: client.licenses.associate_entitlement(slug, seats, 5, overage_percent=20),
    )
    call("client.licenses.associate_entitlement(license, entitlement, UNLIMITED)")
    ensure(
        f"grant of {calls}", lambda: client.licenses.associate_entitlement(slug, calls, UNLIMITED)
    )
    call("client.licenses.associate_entitlement(license, entitlement, True)")
    ensure(f"grant of {sso}", lambda: client.licenses.associate_entitlement(slug, sso, True))

    call(f'client.licenses.list_entitlements("{slug}")')
    for grant in client.licenses.list_entitlements(slug):
        note(
            f"{grant.entitlement_slug}: {grant.value.value}"
            f" (overage {grant.limit_cap_exceeded_overage_percent}%)"
        )

    call(f'client.licenses.get_entitlement("{slug}", "{seats}")')
    granted = client.licenses.get_entitlement(slug, seats)
    cap = enforcement.maximum_allowed_usage(
        granted.value.value if isinstance(granted.value, Number) else 0,
        granted.limit_cap_exceeded_overage_percent,
    )
    done(f"the API will accept usage up to {cap}, and refuse anything above")

    license_id = client.licenses.get(slug).id
    book.state.set("license_id", license_id)

    versions(book, family=slug)


def versions(book: Playbook, *, family: str) -> None:
    """A second version of the license: drafted, put on sale, withdrawn and put back.

    The license above opened a family of the same slug, and the family is what a product is:
    its slug survives new versions, so it is what flags target and what callers store. The
    instance the next steps create stays on version 1 throughout.
    """
    client = book.client
    draft = f"{family}-v2"  # the slug the server would derive; explicit, so a rerun conflicts

    def serving() -> str:
        current = client.license_families.get(family).current_version
        return f"{current.slug} (version {current.version})" if current else "no version"

    def move(transition: Callable[[str], object], name: str, done_as: str) -> None:
        call(f'client.licenses.{name}("{draft}")')
        try:
            transition(draft)
        except ConflictError as error:
            note(f"not moved ({error.code or error.status_code}): an earlier run already did")
            return
        note(f"{done_as}: the family now serves {serving()}")

    note("the license opened a family of the same slug; a new version goes through it")
    call(f'client.licenses.create(..., family_slug="{family}", lifecycle_state="DRAFT")')
    created = ensure(
        f"license version {draft}",
        lambda: client.licenses.create(
            name=book.title("Growth"),
            slug=draft,
            type="PAID",
            family_slug=family,
            lifecycle_state="DRAFT",
            description="The next version of the plan, drafted off sale",
        ),
    )
    book.track("licenses", draft)
    if created is not None:
        note(f"the server numbered it version {created.version}, {created.lifecycle_state}")

    call(f'client.license_families.get("{family}")')
    note(f"the family serves {serving()}: a draft is not on sale")

    move(client.licenses.publish, "publish", "on sale")
    move(client.licenses.archive, "archive", "withdrawn")
    move(client.licenses.unarchive, "unarchive", "back on sale")

    call(f'client.license_families.get("{family}", version=1, include_versions=True)')
    pinned = client.license_families.get(family, version=1, include_versions=True)
    history = ", ".join(f"v{v.version} {v.lifecycle_state}" for v in pinned.versions or [])
    done(f"version 1 stays addressable by number; the history reads {history or 'empty'}")


@step("customer", "A customer, and its link to a CRM")
def customer_step(book: Playbook) -> None:
    client = book.client
    slug = book.slug("acme")
    external = f"crm-{book.run}"

    call("client.customers.create(name=..., slug=..., external_customer_id=..., domain=...)")
    ensure(
        f"customer {slug}",
        lambda: client.customers.create(
            name=book.title("Acme"),
            slug=slug,
            external_customer_id=external,
            domain=f"acme-{book.run}.example",
        ),
    )
    book.track("customers", slug)

    call(f'client.customers.update("{slug}", name=..., external_customer_id=...)')
    client.customers.update(slug, name=book.title("Acme Corp"), external_customer_id=external)

    call(f'client.customers.create_integration("{slug}", "{ADAPTER}", external_id=...)')
    ensure(
        "the CRM link",
        lambda: client.customers.create_integration(
            slug, ADAPTER, external_id=external, metadata={"stage": "trial"}
        ),
    )
    call(f'client.customers.get_integration("{slug}", "{ADAPTER}")')
    client.customers.get_integration(slug, ADAPTER)

    note("a connector reaches the same customer by its id in the third-party system")
    call(f'client.integrations.get_customer("{ADAPTER}", "{external}")')
    client.integrations.get_customer(ADAPTER, external)
    call(f'client.integrations.upsert_customer("{ADAPTER}", "{external}", name=...)')
    client.integrations.upsert_customer(
        ADAPTER, external, name=book.title("Acme Corp"), integration_metadata={"stage": "won"}
    )

    customer = client.customers.get(slug)
    book.state.set("customer_id", customer.id)
    done(f"customer {customer.id}")


@step("product", "A component, a release, and the zone it is deployed to")
def product(book: Playbook) -> None:
    client = book.client
    component_slug, release_slug, zone_slug = (
        book.slug("gateway"),
        book.slug("v1"),
        book.slug("zone"),
    )

    call('client.components.create(name=..., version="1.0.0", slug=...)')
    component = ensure(
        f"component {component_slug}",
        lambda: client.components.create(
            name=book.title("API gateway"),
            version="1.0.0",
            slug=component_slug,
            description="The playbook's only moving part",
        ),
    )
    book.track("components", component_slug)
    component_id = (component or client.components.get(component_slug)).id

    call("client.releases.create(version=..., slug=..., component_ids=[...])")
    ensure(
        f"release {release_slug}",
        lambda: client.releases.create(
            version=f"1.0.0-{book.run}",
            slug=release_slug,
            description="What the zone runs",
            component_ids=[component_id],
        ),
    )
    book.track("releases", release_slug)
    release_id = client.releases.get(release_slug).id

    call('client.deployment_zones.create(name=..., type="development", release_id=...)')
    ensure(
        f"deployment zone {zone_slug}",
        lambda: client.deployment_zones.create(
            name=book.title("Playground"),
            slug=zone_slug,
            type="development",
            description="Where the playbook's instance runs",
            metadata={},
            release_id=release_id,
        ),
    )
    book.track("deployment_zones", zone_slug)

    note("updating a component replaces it: the version moves, the slug cannot")
    call(f'client.components.update("{component_slug}", name=..., version="1.0.1")')
    client.components.update(
        component_slug,
        name=book.title("API gateway"),
        version="1.0.1",
        description="The playbook's only moving part",
    )

    zone = client.deployment_zones.get(zone_slug)
    book.state.set("zone_id", zone.id)
    done(f"zone {zone.slug} runs release {zone.release_id}")


@step("metadata", "A typed metadata field instances must satisfy")
def metadata(book: Playbook) -> None:
    client = book.client
    key = book.slug("region")

    call('client.metadata_fields.create(resource_type="INSTANCE", key=..., json_schema=...)')
    created = ensure(
        f"metadata field {key}",
        lambda: client.metadata_fields.create(
            resource_type="INSTANCE",
            key=key,
            label="Playbook region",
            json_schema={"type": "string", "enum": ["eu-west-1", "us-east-1"]},
        ),
    )
    fields = client.metadata_fields.list("INSTANCE")
    field_id = created.id if created else next(f.id for f in fields if f.key == key)
    book.state.set("metadata_field", {"id": field_id, "key": key})
    book.track("metadata_fields", field_id)

    note("a schema change can be rehearsed before it refuses anybody's data")
    call(
        f'client.metadata_fields.dry_run("{field_id}", {{"type": "string", "enum": ["eu-west-1"]}})'
    )
    impact = client.metadata_fields.dry_run(field_id, {"type": "string", "enum": ["eu-west-1"]})
    note(f"{impact.count} existing resources would stop satisfying the stricter schema")

    call(f'client.metadata_fields.update("{field_id}", resource_type=..., key=..., label=...)')
    client.metadata_fields.update(
        field_id,
        resource_type="INSTANCE",
        key=key,
        label="Hosting region",
        json_schema={"type": "string", "enum": ["eu-west-1", "us-east-1"]},
    )

    note("reordering takes every field, so sending the current order changes nothing")
    call("client.metadata_fields.reorder([field.id for field in fields])")
    client.metadata_fields.reorder([field.id for field in fields])
    done(f"instances may now carry {key}")


@step("instance", "An instance of your product, for that customer")
def instance(book: Playbook) -> None:
    client = book.client
    slug = book.slug("production")
    started = datetime.now(timezone.utc)
    metadata_field = book.state.get("metadata_field", {})
    instance_metadata = {metadata_field["key"]: "eu-west-1"} if metadata_field else {}

    call("client.instances.create(name=..., customer_id=..., license_id=..., start/end dates)")
    ensure(
        f"instance {slug}",
        lambda: client.instances.create(
            name=book.title("Production"),
            slug=slug,
            customer_id=book.state.get("customer_id"),
            license_id=book.state.get("license_id"),
            deployment_zone_id=book.state.get("zone_id"),
            start_license_date=started,
            end_license_date=started + timedelta(days=365),
            description="The instance the playbook meters",
            metadata=instance_metadata,
        ),
    )
    book.track("instances", slug)

    call(f'client.instances.get("{slug}")')
    created = client.instances.get(slug)
    note(
        f"{created.name}: customer {created.customer_slug}, license {created.license_slug}, "
        f"zone {created.deployment_zone_slug}, status {created.status}"
    )

    call(f'client.instances.update_status("{slug}", "DEGRADED")')
    client.instances.update_status(slug, "DEGRADED")
    call(f'client.instances.update_lifecycle_stage("{slug}", "TRIAL")')
    client.instances.update_lifecycle_stage(slug, "TRIAL")
    done("status and lifecycle stage move on their own, without touching the rest")

    call(f'client.instances.create_integration("{slug}", "{ADAPTER}", external_id=...)')
    ensure(
        "the instance's CRM link",
        lambda: client.instances.create_integration(
            slug, ADAPTER, external_id=f"inst-{book.run}", metadata={"plan": "growth"}
        ),
    )
    call(f'client.integrations.get_instance("{ADAPTER}", "inst-{book.run}")')
    client.integrations.get_instance(ADAPTER, f"inst-{book.run}")


@step("usage", "Meter usage, until the license refuses a report")
def usage(book: Playbook) -> None:
    client = book.client
    instance_slug, seats, group = book.slug("production"), book.slug("seats"), book.slug("quotas")

    call(f'client.instances.report_usage("{instance_slug}", "{seats}", 1)')
    refused = False
    for attempt in range(1, 10):
        try:
            reading = client.instances.report_usage(instance_slug, seats, 1)
        except ThresholdExceededError as error:
            done(f"report {attempt} was refused: {error.detail or error.code}")
            refused = True
            break
        note(f"report {attempt}: usage is now {amount(reading)}")
    if not refused:
        warn("the cap was never reached -- is this instance on the playbook's license?")

    call(f'client.instances.get_usage("{instance_slug}", "{seats}")')
    reading = client.instances.get_usage(instance_slug, seats)
    used = amount(reading) or 0.0
    granted = client.licenses.get_entitlement(book.slug("growth"), seats)
    included = granted.value.value if isinstance(granted.value, Number) else 0.0
    overage = granted.limit_cap_exceeded_overage_percent
    note(f"{used} of {included} used, {enforcement.percentage_used(included, used)}% of the plan")
    note(f"{enforcement.remaining(included, used, overage)} left before reports are refused")

    note("a 'set' report writes the total, which is how to correct it downwards")
    call(f'client.instances.report_usage("{instance_slug}", "{seats}", 2, behavior="set")')
    corrected = client.instances.report_usage(instance_slug, seats, 2, behavior="set")
    done(f"usage is back to {amount(corrected)}")

    call(f'client.instances.list_usage("{instance_slug}")')
    for row in client.instances.list_usage(instance_slug):
        note(f"{row.entitlement_slug}: {amount(row)}")

    call(f'client.entitlement_groups.get_usage("{group}", "{instance_slug}")')
    for member in client.entitlement_groups.get_usage(group, instance_slug):
        note(f"{member.entitlement_slug} in the group: {member.entitlement_type}")

    call(f'client.instances.list_audit_trails("{instance_slug}", limit=5)')
    for entry in client.instances.list_audit_trails(instance_slug, limit=5):
        note(f"{entry.timestamp:%H:%M:%S}  {entry.event_name}")


def evaluator(book: Playbook) -> OpenFeatureClient | None:
    """Register Kaiten as this process's OpenFeature provider, and return a flag client.

    This SDK has no ``evaluate()``, deliberately. Kaiten implements OFREP, so any OpenFeature
    SDK reads its flags through the generic provider -- which is the point of the protocol:
    the application depends on OpenFeature, not on us. The provider appends ``/ofrep/v1/...``
    to the base URL, so it takes the same URL and the same token as the client above.
    """
    try:
        from openfeature import api
        from openfeature.contrib.provider.ofrep import OFREPProvider
    except ImportError:
        return None

    token = book.token
    api.set_provider(
        OFREPProvider(
            base_url=book.client.base_url,
            headers_factory=lambda: {"Authorization": f"Bearer {token}"} if token else {},
        )
    )
    return api.get_client("playbook")


@step("flags", "A feature flag, defined here and evaluated through OpenFeature")
def flags(book: Playbook) -> None:
    client = book.client
    slug, customer = book.slug("new-checkout"), book.slug("acme")
    variants = [targeting.variant("on", True), targeting.variant("off", False)]
    rules = [
        targeting.rule("The playbook's customer", f"__kaiten.customer.slug == '{customer}'", "on"),
        targeting.split_rule("Everyone else", "true", {"on": 50, "off": 50}),
    ]

    call("client.feature_flags.create(name=..., variants=[...], targetings=[...])")
    try:
        ensure(
            f"feature flag {slug}",
            lambda: client.feature_flags.create(
                name=book.title("New checkout"),
                slug=slug,
                type="boolean",
                variants=variants,
                default_variant="off",
                targetings=rules,
                description="Does this customer get the new checkout?",
                metadata={"playbook": book.run},
            ),
        )
    except APIStatusError as error:
        warn(f"the targeting rule was refused ({error.code or error.status_code}); using 'true'")
        ensure(
            f"feature flag {slug}",
            lambda: client.feature_flags.create(
                name=book.title("New checkout"),
                slug=slug,
                type="boolean",
                variants=variants,
                default_variant="off",
                targetings=[targeting.rule("Everyone", "true", "on")],
            ),
        )
    book.track("feature_flags", slug)

    call("client.feature_flags.manifest()")
    note(f"{len(client.feature_flags.manifest())} flags in the OpenFeature manifest")

    note("the SDK defines flags; it does not evaluate them -- OpenFeature does, over OFREP")
    call("api.set_provider(OFREPProvider(base_url=..., headers_factory=...))")
    flags_client = evaluator(book)
    if flags_client is None:
        warn("skipped: pip install openfeature-sdk openfeature-provider-ofrep to evaluate")
        return

    from openfeature.evaluation_context import EvaluationContext

    context = EvaluationContext(targeting_key=customer, attributes={"region": "eu"})
    call(f'flags.get_boolean_value("{slug}", False, EvaluationContext(targeting_key=...))')
    note(
        f"the new checkout is {'on' if flags_client.get_boolean_value(slug, False, context) else 'off'} for {customer}"
    )

    call(f'flags.get_boolean_details("{slug}", False, context)')
    details = flags_client.get_boolean_details(slug, False, context)
    note(f"value {details.value}, variant {details.variant}, reason {details.reason}")
    note("a failed evaluation returns the default you passed: that is OpenFeature's contract")

    note("disabling a flag is a hard kill switch: no rule is even evaluated")
    call(f'client.feature_flags.update("{slug}", ..., enabled=False)')
    client.feature_flags.update(
        slug,
        name=book.title("New checkout"),
        type="boolean",
        variants=variants,
        default_variant="off",
        targetings=rules,
        enabled=False,
    )
    after = flags_client.get_boolean_details(slug, False, context)
    done(f"now it answers {after.value} with reason {after.reason}")


@step("tokens", "A service account, and a token that works until it is revoked")
def tokens(book: Playbook) -> None:
    client = book.client
    account, token_slug = book.slug("robot"), book.slug("token")

    call("client.service_accounts.create(name=..., slug=...)")
    ensure(
        f"service account {account}",
        lambda: client.service_accounts.create(name=book.title("Robot"), slug=account),
    )
    book.track("service_accounts", account)

    call('client.service_accounts.create_token(account, name=..., scopes=["read:customers"])')
    minted = client.service_accounts.create_token(
        account,
        name=book.title("playbook token"),
        slug=token_slug,
        scopes=["read:customers"],
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    book.track("tokens", f"{account}/{token_slug}")
    secret = required(minted.token, "the token's plaintext")
    note(f"the plaintext is returned once, here and nowhere else: {secret[:8]}...")

    probe = book.new_client(secret)
    try:
        note(f"the minted token reads {len(probe.customers.list())} customers")
    except APIStatusError as error:
        warn(f"the minted token could not read customers: {error}")
    finally:
        probe.close()

    call(f'client.service_accounts.list_tokens("{account}")')
    note(f"{len(client.service_accounts.list_tokens(account))} live tokens on the account")

    call(f'client.service_accounts.delete_token("{account}", "{token_slug}")')
    client.service_accounts.delete_token(account, token_slug)
    revoked = book.new_client(secret)
    try:
        revoked.customers.list()
        warn("the revoked token still answers -- that is worth reporting")
    except AuthenticationError:
        done("the revoked token is refused immediately, on every replica")
    except APIStatusError as error:
        note(f"the revoked token now fails with {error.status_code}")
    finally:
        revoked.close()


@step("webhooks", "Verify a delivery, with nothing on the network")
def webhooks(book: Playbook) -> None:
    secret = "whsec_" + base64.b64encode(b"playbook-signing-secret-0123456").decode()
    payload = json.dumps(
        {
            "name": "INSTANCE_ENTITLEMENT_CAP_EXCEEDED",
            "type": "com.kaiten.instance.entitlement.v1.cap_exceeded",
            "data": {
                "entitlement_slug": book.slug("seats"),
                "threshold": 5,
                "value": 6,
                "overage": 1,
            },
        }
    ).encode()
    headers = sign(payload, secret)

    note("this is the delivery Kaiten would send when usage crosses the included value")
    call("kaitencloud.webhooks.verify_webhook(payload, headers, secret=...)")
    event = verify_webhook(payload, headers, secret=secret)
    if isinstance(event, InstanceEntitlementCapExceededEvent):
        done(f"{event.name}: {event.data.entitlement_slug} is {event.data.overage} over its cap")

    call("verify_webhook(tampered_payload, headers, secret=...)")
    try:
        verify_webhook(payload.replace(b'"overage": 1', b'"overage": 9'), headers, secret=secret)
        warn("a tampered payload verified -- that should never happen")
    except WebhookVerificationError as error:
        done(f"a tampered payload is refused: {error}")


@step("platform", "The Platform API, if a ksm_ credential is configured")
def platform(book: Playbook) -> None:
    if book.platform is None:
        note("skipped: set KAITEN_PLATFORM_BASE_URL and KAITEN_PLATFORM_TOKEN to include it")
        return

    call("platform.me()")
    credential = book.platform.me()
    note(f"{credential.name} ({credential.credential_kind}), subject {credential.subject}")
    note(f"scopes: {', '.join(credential.scopes or []) or 'none'}")

    if not book.platform_org:
        note("pass --platform-org <uuid> to also read an organization and mint a token in it")
        return

    org = book.platform_org
    call(f'platform.organizations.get("{org}")')
    note(f"organization {book.platform.organizations.get(org).name}")

    note("a platform credential never acts inside an organization: it mints a token that does")
    call("platform.tokens.mint(org, name=..., scopes=[...], ttl=timedelta(minutes=15))")
    minted = book.platform.tokens.mint(
        org,
        name=book.title("platform token"),
        scopes=["read:customers"],
        ttl=timedelta(minutes=15),
    )
    slug = required(minted.slug, "the minted token's slug")
    note(f"minted {slug}; its plaintext exists only in this response")

    call(f'platform.tokens.list("{org}")')
    note(f"{len(book.platform.tokens.list(org))} tokens this credential holds in that organization")

    call(f'platform.tokens.revoke("{org}", "{slug}")')
    book.platform.tokens.revoke(org, slug)
    done("minted, listed and revoked -- revoking the parent would have taken it anyway")


@step("cleanup", "Delete everything this run created")
def cleanup(book: Playbook) -> None:
    client = book.client

    # In dependency order: an instance holds a license, a zone holds a release.
    deletions: list[tuple[str, str, Callable[[str], object]]] = [
        ("feature_flags", "feature flag", client.feature_flags.delete),
        ("instances", "instance", client.instances.delete),
        ("licenses", "license", client.licenses.delete),
        ("customers", "customer", client.customers.delete),
        ("entitlements", "entitlement", client.entitlements.delete),
        ("entitlement_groups", "entitlement group", client.entitlement_groups.delete),
        ("deployment_zones", "deployment zone", client.deployment_zones.delete),
        ("releases", "release", client.releases.delete),
        ("components", "component", client.components.delete),
    ]
    for kind, label, delete in deletions:
        for identifier in book.created(kind):
            forget(f"{label} {identifier}", partial(delete, identifier))

    for field_id in book.created("metadata_fields"):
        note("metadata fields are archived, never deleted: archiving frees the key")
        forget(f"metadata field {field_id}", partial(client.metadata_fields.archive, field_id))

    if book.created("service_accounts"):
        warn(
            "service accounts have no delete endpoint: "
            f"{', '.join(book.created('service_accounts'))} stays, with no live token"
        )

    book.state.clear()
    done("the state file is gone; the next run starts fresh")


def forget(what: str, delete: Callable[[], object]) -> None:
    try:
        delete()
    except NotFoundError:
        note(f"{what} was already gone")
    except APIStatusError as error:
        warn(f"could not delete {what}: {error}")
    else:
        done(f"deleted {what}")


def sign(payload: bytes, secret: str) -> dict[str, str]:
    """The headers Kaiten's webhook delivery carries, so the step can verify a real one."""
    timestamp = str(int(time.time()))
    key = base64.b64decode(secret.removeprefix("whsec_"))
    digest = hmac.new(key, f"msg_playbook.{timestamp}.".encode() + payload, hashlib.sha256)
    return {
        "svix-id": "msg_playbook",
        "svix-timestamp": timestamp,
        "svix-signature": "v1," + base64.b64encode(digest.digest()).decode(),
    }


# --------------------------------------------------------------------------------------------
# Running them
# --------------------------------------------------------------------------------------------


def parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="playbook.py",
        description="A scripted walk through a Kaiten deployment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="steps: " + ", ".join(step.name for step in STEPS),
    )
    parser.add_argument("steps", nargs="*", help="the steps to run (default: all but cleanup)")
    parser.add_argument("--list", action="store_true", help="list the steps and exit")
    parser.add_argument("--from", dest="start", metavar="STEP", help="resume at this step")
    parser.add_argument("--pause", action="store_true", help="wait for Enter before each step")
    parser.add_argument("--base-url", help="the API, e.g. http://localhost:6000")
    parser.add_argument("--token", help="an organization token (ksh_...)")
    parser.add_argument("--platform-org", metavar="UUID", help="mint a token in this organization")
    parser.add_argument("--state", type=Path, default=STATE_FILE, help="where the run is recorded")
    parser.add_argument("--verbose", action="store_true", help="log retries and fallbacks")
    return parser.parse_args(argv)


def chosen(args: argparse.Namespace) -> list[Step]:
    names = [step.name for step in STEPS]
    for name in args.steps:
        if name not in names:
            raise SystemExit(f"unknown step {name!r}; try --list")
    if args.steps:
        return [step for step in STEPS if step.name in args.steps]

    running = [step for step in STEPS if step.name != "cleanup"]
    if args.start:
        if args.start not in names:
            raise SystemExit(f"unknown step {args.start!r}; try --list")
        started = [step.name for step in running].index(args.start)
        return running[started:]
    return running


def build(args: argparse.Namespace) -> Playbook:
    client = KaitenClient(base_url=args.base_url, token=args.token)
    platform_url = os.environ.get("KAITEN_PLATFORM_BASE_URL")
    platform_token = os.environ.get("KAITEN_PLATFORM_TOKEN")
    platform_client = (
        KaitenPlatformClient(base_url=platform_url, token=platform_token)
        if platform_url and platform_token
        else None
    )
    return Playbook(
        client=client,
        state=State(args.state),
        platform=platform_client,
        platform_org=args.platform_org,
        token=args.token or os.environ.get("KAITEN_AUTH_TOKEN"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse(argv)
    if args.list:
        for number, step in enumerate(STEPS, 1):
            print(f"{number:>3}. {paint(step.name, '1')}  {step.title}")
        return 0
    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    steps = chosen(args)
    try:
        book = build(args)
    except (CredentialError, ValueError) as error:  # no address, no token, or a malformed one
        raise SystemExit(f"{error}\nSee examples/README.md, Before you start.") from None
    heading(f"Kaiten playbook {book.run} against {book.client.base_url}")

    for number, step in enumerate(steps, 1):
        heading(f"{number}/{len(steps)}  {step.name} -- {step.title}")
        if args.pause:
            input(paint("   Enter to run this step, Ctrl-C to stop ", "2"))
        try:
            step.run(book)
        except KeyboardInterrupt:
            print()
            warn(f"stopped; resume with --from {step.name}")
            return 130
        except (APIStatusError, PlaybookError) as error:
            report(error)
            warn(f"resume with --from {step.name} once it is sorted out")
            return 1

    heading("Done")
    note(f"what this run created is listed in {args.state}")
    if any(step.name == "cleanup" for step in steps):
        return 0
    note(f"delete it all with: python {sys.argv[0]} cleanup")
    return 0


def report(error: Exception) -> None:
    if isinstance(error, APIStatusError):
        warn(f"{error}")
        if error.error_id:
            note(f"quote errorId {error.error_id} in a bug report")
        if isinstance(error, PermissionDeniedError):
            note("this token is missing a scope for that operation")
        return
    warn(str(error))


if __name__ == "__main__":
    sys.exit(main())
