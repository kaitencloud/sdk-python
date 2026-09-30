<div align="center">

# Kaiten Python SDK

**The official Python client for [Kaiten](https://kaiten.sh), the control plane of your SaaS:<br>
customers, instances, licenses, entitlements, usage metering, feature flags and releases.**

[![PyPI](https://img.shields.io/pypi/v/kaitencloud.svg?label=pypi&color=4c1)](https://pypi.org/project/kaitencloud/)
[![Python](https://img.shields.io/pypi/pyversions/kaitencloud.svg)](https://pypi.org/project/kaitencloud/)
[![CI](https://github.com/kaitencloud/sdk-python/actions/workflows/ci.yml/badge.svg)](https://github.com/kaitencloud/sdk-python/actions/workflows/ci.yml)
[![Typed](https://img.shields.io/badge/typing-mypy%20strict-2a6db2.svg)](https://peps.python.org/pep-0561/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

[Documentation](https://docs.kaiten.sh) · [Changelog](CHANGELOG.md) · [Report a bug](https://github.com/kaitencloud/sdk-python/issues)

</div>

---

```python
from kaitencloud import KaitenClient

client = KaitenClient(token="ksh_...")

for customer in client.customers.list():
    print(customer.name)

client.instances.report_usage("acme-production", "seats", 1)
```

## Why this SDK

- **Typed end to end.** Every response is a pydantic model generated from Kaiten's OpenAPI
  contract; the package ships `py.typed` and passes `mypy --strict`.
- **Sync and async, identical.** `KaitenClient` and `AsyncKaitenClient` expose the same methods
  with the same signatures — the sync client is generated from the async one.
- **Complete lists.** `list()` walks every page for you, and refuses to hand back a list the API
  said was incomplete.
- **Retries that never double-bill.** Only requests that are safe to repeat are retried. A usage
  report is never sent twice.
- **Errors you can act on.** Every failure is a typed exception carrying the API's RFC 9457
  problem: `code`, `detail`, `error_id`.
- **Both APIs.** The Core API your product talks to, and the Platform API that provisions
  organizations and mints their tokens.
- **Webhooks included.** Svix signatures verified, all 55 event types parsed into models.
- **Flags through OpenFeature.** Kaiten speaks OFREP, so flags are defined here and
  evaluated with the [OpenFeature SDK](#feature-flags) — a vendor-neutral API, not ours.
- **Contract-tested.** All 108 operations the SDK wraps are exercised against the contract, and
  every request body is validated against the API's own schema.

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Guide](#guide)
  - [Catalog and licenses](#catalog-and-licenses) · [Customers and instances](#customers-and-instances) · [Usage metering](#usage-metering)
  - [Feature flags](#feature-flags) · [Releases and deployment zones](#releases-and-deployment-zones) · [Webhooks](#webhooks)
  - [The Platform API](#the-platform-api)
- [The playbook](#the-playbook)
- [Working with the SDK](#working-with-the-sdk): [pagination](#pagination) · [errors](#errors) · [retries and timeouts](#retries-and-timeouts) · [models](#models) · [logging](#logging)
- [API reference](#api-reference)
- [How the SDK stays true to the API](#how-the-sdk-stays-true-to-the-api)
- [Development](#development)

## Installation

```bash
pip install kaitencloud
```

or, with [uv](https://docs.astral.sh/uv/):

```bash
uv add kaitencloud
```

The SDK supports Python 3.10 to 3.14, and depends only on `httpx`, `pydantic` v2 and
`typing-extensions`.

## Quick start

Create an organization token (`ksh_...`) from a service account in the Kaiten console, then
point the client at your deployment:

```python
from kaitencloud import KaitenClient

client = KaitenClient(
    base_url="https://kaiten.example.com",  # or set KAITEN_BASE_URL
    token="ksh_...",  # or set KAITEN_AUTH_TOKEN
)

# Every customer, however many pages it takes.
for customer in client.customers.list():
    print(customer.slug, customer.name)

# What an instance consumes, next to what its license grants.
for meter in client.instances.list_usage("acme-production"):
    granted = meter.limit.value if meter.limit else "not granted"
    print(f"{meter.entitlement_slug}: {meter.value.value} of {granted}")
```

With `KAITEN_BASE_URL` and `KAITEN_AUTH_TOKEN` set, a client needs no arguments, and the rest
of this README assumes they are. The async client is the same API, awaited:

```python
import asyncio

from kaitencloud import AsyncKaitenClient


async def main() -> None:
    async with AsyncKaitenClient() as client:
        customers, instances = await asyncio.gather(
            client.customers.list(),
            client.instances.list(),
        )
        print(f"{len(customers)} customers, {len(instances)} instances")


asyncio.run(main())
```

### The model in one picture

```text
Organization              you: a SaaS vendor using Kaiten
└── Customer              client.customers         a client of yours
    └── Instance          client.instances         a deployment of your product for that customer
        ├── License       client.licenses          the contract it runs under, granting values
        │                 client.entitlements      ...of the entitlements in your catalog
        ├── Usage         client.instances.report_usage()   what it consumed
        └── Zone          client.deployment_zones  where it runs, and the release deployed there
                          client.releases → client.components
```

## Configuration

| Argument | Environment variable | Default | |
| --- | --- | --- | --- |
| `token` | `KAITEN_AUTH_TOKEN` | *required* | A string, or a callable returning one before each request |
| `base_url` | `KAITEN_BASE_URL` | *required* | Your deployment's address; `/api` is appended when missing |
| `timeout` | | 30 s (10 s to connect) | Seconds, or an `httpx.Timeout` |
| `max_retries` | | `2` | Retries of a failed request that is safe to repeat |
| `default_headers` | | | Headers sent with every request |
| `http_client` | | | Your own `httpx.Client` / `httpx.AsyncClient`: proxies, TLS, transports |

Both clients are context managers, and closing one closes the connection pool it created —
never one you passed in.

### Credentials

Kaiten has several kinds of credential, and each API refuses the others with a deliberately
vague error. The SDK recognizes them and raises a clear `CredentialError` *before* sending
anything when one ends up in the wrong place.

| Credential | Looks like | Use it with |
| --- | --- | --- |
| Organization token | `ksh_...` | `KaitenClient` |
| Identity-provider JWT | `eyJ...` | `KaitenClient` |
| Platform credential | `ksm_...` | `KaitenPlatformClient` |
| Webhook signing secret | `whsec_...` | `kaitencloud.webhooks` |

A credential that rotates can be supplied as a callable — it is read before every request, so
there is no client to rebuild:

```python
client = KaitenClient(token=lambda: vault.read("kaiten/token"))
```

## Guide

### Catalog and licenses

An **entitlement** says what can be granted and how its usage is measured. A **license** grants
values of entitlements. A numeric grant carries its own enforcement: `overage_percent=0` is a
hard limit, `10` tolerates 10% over the granted value before usage reports are refused.

```python
from kaitencloud import UNLIMITED, KaitenClient

client = KaitenClient()

client.entitlements.create(
    name="Seats",
    slug="seats",
    type="NUMBER",
    unit_singular="seat",
    unit_plural="seats",
    user_facing=True,
)
client.entitlements.create(name="Single sign-on", slug="sso", type="BOOLEAN")
client.entitlements.create(name="API calls", slug="api-calls", type="NUMBER", reset_period="MONTH")

client.licenses.create(name="Growth", slug="growth", type="PAID")
client.licenses.associate_entitlement("growth", "seats", 50, overage_percent=10)
client.licenses.associate_entitlement("growth", "sso", True)
client.licenses.associate_entitlement("growth", "api-calls", UNLIMITED)
```

A granted value is a `bool` for a BOOLEAN entitlement, a number for a NUMBER one, and a `dict`
for a CONFIG one.

A license is one **version** of a product, its **license family**. Creating a license without
naming a family opens a new one: `growth` above is version 1 of the family `growth`. To change
what a plan grants without touching the customers already on it, add a version to the family,
build it as a draft, and put it on sale when it is ready:

```python
client.licenses.create(name="Growth", type="PAID", family_slug="growth", lifecycle_state="DRAFT")
client.licenses.associate_entitlement("growth-v2", "seats", 100, overage_percent=10)
client.licenses.publish("growth-v2")

family = client.license_families.get("growth")  # now resolves to growth-v2
```

A new version's slug is `<family>-v<version>`, and its number is assigned by the server. A
family resolves to its default version if it has one, otherwise to its highest-numbered
published version — so store the family slug, which survives renames and new versions, rather
than a version's. `license_families.get("growth", version=1)` pins a version whatever its state,
and `include_versions=True` adds the whole history. `licenses.archive()` withdraws a version
from sale: the instances already on it keep it, and no new one can take it until
`licenses.unarchive()`.

### Customers and instances

```python
from datetime import datetime, timezone

acme = client.customers.create(name="Acme", slug="acme", domain="acme.com")
growth = client.licenses.get("growth")

client.instances.create(
    name="Acme production",
    slug="acme-production",
    customer_id=acme.id,
    license_id=growth.id,
    start_license_date=datetime(2026, 9, 1, tzinfo=timezone.utc),
    end_license_date=datetime(2027, 9, 1, tzinfo=timezone.utc),
    metadata={"region": "eu-west-1"},
)

client.instances.update_status("acme-production", "DEGRADED")
client.instances.update_lifecycle_stage("acme-production", "AT_RISK")
```

> **Note** — `update()` methods are full replacements, as the API's `PUT` is: send every field
> you want to keep. Datetimes must be timezone-aware: the SDK refuses to guess the zone of a
> license term.

### Usage metering

```python
from kaitencloud import ThresholdExceededError

try:
    client.instances.report_usage("acme-production", "seats", 1)
except ThresholdExceededError as error:
    # Refused at the cap: the granted value plus its overage allowance. Nothing was recorded.
    print("Time to upgrade:", error.detail)
```

`behavior="append"` (the default) folds the value into the total through the entitlement's
aggregation method; `behavior="set"` replaces the total, which is also how to correct it.

`kaitencloud.usage` computes the same boundaries the server enforces, to render a meter or check
a report before sending it:

```python
from kaitencloud import usage

grant = client.licenses.get_entitlement("growth", "seats")
current = client.instances.get_usage("acme-production", "seats")
included, used = grant.value.value, current.value.value

usage.maximum_allowed_usage(included, grant.limit_cap_exceeded_overage_percent)  # 55.0
usage.remaining(included, used, grant.limit_cap_exceeded_overage_percent)  # left before refusal
usage.percentage_used(included, used)  # passes 100 once the allowance is in use
```

### Feature flags

Define flags with the builders in `kaitencloud.targeting`. Targeting rules are CEL expressions,
evaluated in order; the first match wins. Kaiten fills the reserved `__kaiten` namespace itself:
evaluate with a customer's slug as the targeting key, and a rule can read the license and the
entitlements that customer holds.

```python
from kaitencloud import targeting

client.feature_flags.create(
    name="New checkout",
    slug="new-checkout",
    type="boolean",
    variants=[targeting.variant("on", True), targeting.variant("off", False)],
    default_variant="off",
    targetings=[
        targeting.rule("Growth plan", "__kaiten.license.familySlug == 'growth'", "on"),
        targeting.split_rule("Progressive rollout", "true", {"on": 10, "off": 90}),
    ],
)
```

**This SDK does not evaluate flags, on purpose.** Kaiten implements
[OFREP](https://openfeature.dev/specification/appendix-c), the OpenFeature Remote Evaluation
Protocol, so evaluation belongs to [OpenFeature](https://openfeature.dev) itself: install the
SDK and the generic OFREP provider, point it at the same base URL with the same token, and your
application talks to a vendor-neutral API it already knows.

```bash
pip install openfeature-sdk openfeature-provider-ofrep
```

```python
from openfeature import api
from openfeature.contrib.provider.ofrep import OFREPProvider
from openfeature.evaluation_context import EvaluationContext

api.set_provider(
    OFREPProvider(
        base_url="https://kaiten.example.com/api",  # the provider appends /ofrep/v1/...
        headers_factory=lambda: {"Authorization": "Bearer ksh_..."},
    )
)

flags = api.get_client("checkout")
context = EvaluationContext(targeting_key="acme", attributes={"region": "eu"})

if flags.get_boolean_value("new-checkout", False, context):
    ...

details = flags.get_boolean_details("new-checkout", False, context)
print(details.value, details.variant, details.reason)
```

The targeting key is the subject rollouts bucket on — a customer slug, a user id — and it is
what the reserved `__kaiten` namespace resolves against, so a rule can read the license and the
entitlements that subject holds. Splits are sticky: a subject keeps its variant from one
evaluation to the next. A failed evaluation returns the default you passed rather than raise,
which is OpenFeature's contract, not ours.

`client.feature_flags.manifest()` returns the OpenFeature manifest — every flag, its type and
its default — for tooling that generates typed accessors from flag definitions.

### Releases and deployment zones

```python
gateway = client.components.create(name="api-gateway", version="v1.4.0")
release = client.releases.create(version="v1.4.0", component_ids=[gateway.id])

# Pointing a zone at a release records the deployment.
client.deployment_zones.update(
    "eu-west-1", name="AWS eu-west-1", type="production", release_id=release.id
)
```

Releases are immutable: changing one means deleting it and creating another.

### Webhooks

Kaiten delivers webhooks through [Svix](https://www.svix.com). `verify_webhook()` checks the
signature and the timestamp of a delivery, then returns its event as a typed model:

```python
import os

from fastapi import FastAPI, Request, Response
from kaitencloud.webhooks import (
    CustomerCreatedEvent,
    InstanceEntitlementCapExceededEvent,
    WebhookVerificationError,
    verify_webhook,
)

app = FastAPI()


@app.post("/webhooks/kaiten")
async def kaiten_webhook(request: Request) -> Response:
    try:
        event = verify_webhook(
            await request.body(),  # the raw body: parsing it first would change the signed bytes
            request.headers,
            secret=os.environ["KAITEN_WEBHOOK_SECRET"],
        )
    except WebhookVerificationError:
        return Response(status_code=400)

    match event:
        case InstanceEntitlementCapExceededEvent(data=cap):
            alert_account_manager(cap.entitlement_slug, cap.overage)
        case CustomerCreatedEvent(data=customer):
            send_welcome(customer.name)

    return Response(status_code=204)
```

Every event the API publishes has a model named after it, from `ComponentCreatedEvent` to
`ReleaseDeletedEvent`. An event newer than the SDK you run parses as `UnknownWebhookEvent`
instead of failing.

### The Platform API

The Platform API administers a whole Kaiten deployment. It listens on its own port, on no
public route, and accepts only a platform credential (`ksm_...`).

```python
from datetime import timedelta

from kaitencloud import KaitenPlatformClient

platform = KaitenPlatformClient(base_url="http://kaiten-api.kaiten.svc:6001", token="ksm_...")

# Idempotent: the organization's id derives from the identity provider's id.
org = platform.organizations.ensure(external_id="org_2abcDEF", name="Acme")

# A platform credential never acts inside an organization: it mints a token that does.
minted = platform.tokens.mint(
    org.id, name="billing-sync-v2", scopes=["write:instances"], ttl=timedelta(days=90)
)
store_secret(minted.token)  # the plaintext exists in this response only
```

> **Revocation cascades.** Revoking a platform credential revokes every token it minted, so
> rotate by minting the new token, adopting it, then revoking the old one. And `revoke()` takes
> the token's server-generated **slug**, which `tokens.list()` maps back from the name you chose.

```python
old = next(token for token in platform.tokens.list(org.id) if token.name == "billing-sync-v1")
platform.tokens.revoke(org.id, old.slug)
```

A connector hosted outside Kaiten registers itself on every start — registration is an upsert:

```python
platform.connectors.register(
    name="kaiten.integration.crm.acme",
    version="1.2.0",
    settings_schema={
        "type": "object",
        "properties": {
            "apiKey": {"type": "string", "writeOnly": True}
        },  # a secret: never read back
    },
    entitlement_slug="crm-sync",  # the BOOLEAN entitlement a license must grant to activate it
)
```

## The playbook

[`examples/playbook.py`](examples/playbook.py) is a guided tour of a deployment of your own:
thirteen steps that build a catalog, a license, a customer and an instance, meter usage until the
license refuses a report, evaluate a feature flag, mint and revoke a token and verify a webhook
signature — then delete everything they made. Each step prints the call before it makes it, so
the script reads as documentation that runs, one step at a time.

```bash
uv run python examples/playbook.py --list
```

[**`examples/README.md`**](examples/README.md) is the guide to it: what each step covers, how to
pause and resume a run, what it records about itself, and how `cleanup` deletes only what that
run created.

## Working with the SDK

### Pagination

Every `list()` returns the **whole** collection: the SDK walks the cursor at the largest page
size the API accepts. If the API ever reports more rows without a usable cursor, `list()` raises
`PaginationError` rather than return a list it knows is partial.

The audit trail grows without bound, so it takes a ceiling instead:

```python
entries = client.instances.list_audit_trails(
    "acme-production", event_name="INSTANCE_STATUS_CHANGED", limit=100
)
```

### Errors

Every exception derives from `KaitenError`:

```text
KaitenError
├── CredentialError              a credential is missing, or in the wrong place (raised before sending)
├── APIConnectionError           the API could not be reached
│   └── APITimeoutError
├── APIStatusError               the API answered with a non-2xx status
│   ├── BadRequestError              400
│   ├── AuthenticationError          401  missing, expired or revoked credential
│   ├── PermissionDeniedError        403  a scope is missing
│   ├── NotFoundError                404
│   ├── ConflictError                409
│   │   └── ThresholdExceededError       a usage report refused at the cap
│   ├── UnprocessableEntityError     422
│   ├── RateLimitError               429
│   ├── InternalServerError          5xx
│   │   └── ServiceUnavailableError      503
│   └── FlagEvaluationError          a flag could not be evaluated
├── APIResponseValidationError   a 2xx response that breaks the contract
├── PaginationError              a list the API reported as incomplete
├── WebhookVerificationError     a webhook that fails verification
└── WebhookPayloadError          an authentic webhook that breaks its event contract
```

An `APIStatusError` keeps everything the API said. Branch on `code` rather than on the status:
a 409 for a reached limit and a 409 for a taken slug share a status, not a meaning.

```python
from kaitencloud import APIStatusError

try:
    client.customers.create(name="Acme", slug="acme")
except APIStatusError as error:
    print(error.status_code, error.code, error.detail)
    print("Quote this in a support request:", error.error_id)
```

### Retries and timeouts

A request that fails on a connection error, a 408, a 429 or a 5xx is retried with exponential
backoff and jitter, honouring `Retry-After` — but only when repeating it is safe:

| Request | Retried |
| --- | --- |
| `GET`, `PUT`, `DELETE` | ✓ |
| Flag evaluations, instance status and lifecycle updates, metadata dry runs and reorders, `organizations.ensure()`, `connectors.register()` | ✓ — they converge |
| Any other `POST` or `PATCH`: creations, usage reports, upserts | only if the connection never opened |
| A `401` or `403` | never |

Tune it per client, or per call with `with_options()`, which shares the connection pool:

```python
import httpx

client = KaitenClient(timeout=10.0, max_retries=4)
client.with_options(timeout=1.0, max_retries=0).customers.get("acme")

proxied = KaitenClient(http_client=httpx.Client(proxy="http://proxy.internal:3128"))
```

### Models

Responses are pydantic models with snake_case attributes. They are lenient where the API grows:
a field added after your SDK release lands in `model_extra`, and an unknown enum value parses as a
plain string instead of failing.

```python
instance = client.instances.get("acme-production")

instance.customer_slug  # typed attributes
instance.start_license_date  # a timezone-aware datetime
instance.to_dict()  # the exact wire shape, camelCase keys included
instance.model_extra  # fields newer than this SDK
```

All models, and the typed dictionaries methods accept, are importable from `kaitencloud.types`.

### Logging

The SDK logs to the `kaitencloud` logger: retries at `INFO`, flag evaluations that fell back to
their default at `WARNING`. Credentials are never logged.

```python
import logging

logging.getLogger("kaitencloud").setLevel(logging.INFO)
```

## API reference

The Core API clients cover 98 of its 107 operations. Of the nine left out, three are
rule-editor tooling for the Kaiten console, four are a signed-in person's own notification feed
and preferences — which an API token has no equivalent of — and two are the OFREP evaluation
endpoints, which an [OpenFeature provider](#feature-flags) calls. The Platform API clients cover
all 10 of its operations. The async clients have the same methods.

<details>
<summary><b>client.components</b> · <b>client.connectors</b> · <b>client.customers</b></summary>

| Method | Operation |
| --- | --- |
| `client.components.list()` | `GET /components` |
| `client.components.get()` | `GET /components/{componentSlug}` |
| `client.components.create()` | `POST /components` |
| `client.components.update()` | `PUT /components/{componentSlug}` |
| `client.components.delete()` | `DELETE /components/{componentSlug}` |
| `client.connectors.list()` | `GET /connectors` |
| `client.connectors.get()` | `GET /connectors/{connectorName}` |
| `client.connectors.get_state()` | `GET /connectors/{connectorName}/state` |
| `client.connectors.activate()` | `PUT /connectors/{connectorName}/activation` |
| `client.connectors.deactivate()` | `DELETE /connectors/{connectorName}/activation` |
| `client.connectors.get_settings_schema()` | `GET /connectors/{connectorName}/settings/schema` |
| `client.connectors.get_settings()` | `GET /connectors/{connectorName}/settings` |
| `client.connectors.update_settings()` | `PUT /connectors/{connectorName}/settings` |
| `client.connectors.delete_settings()` | `DELETE /connectors/{connectorName}/settings` |
| `client.customers.list()` | `GET /customers` |
| `client.customers.get()` | `GET /customers/{customerSlug}` |
| `client.customers.create()` | `POST /customers` |
| `client.customers.update()` | `PUT /customers/{customerSlug}` |
| `client.customers.delete()` | `DELETE /customers/{customerSlug}` |
| `client.customers.get_integration()` | `GET /customers/{customerSlug}/integrations/{integrationName}` |
| `client.customers.create_integration()` | `POST /customers/{customerSlug}/integrations/{integrationName}` |
| `client.customers.update_integration()` | `PUT /customers/{customerSlug}/integrations/{integrationName}` |
| `client.customers.delete_integration()` | `DELETE /customers/{customerSlug}/integrations/{integrationName}` |

</details>

<details>
<summary><b>client.deployment_zones</b> · <b>client.entitlement_groups</b> · <b>client.entitlements</b></summary>

| Method | Operation |
| --- | --- |
| `client.deployment_zones.list()` | `GET /deployment-zones` |
| `client.deployment_zones.get()` | `GET /deployment-zones/{deploymentZoneSlug}` |
| `client.deployment_zones.create()` | `POST /deployment-zones` |
| `client.deployment_zones.update()` | `PUT /deployment-zones/{deploymentZoneSlug}` |
| `client.deployment_zones.delete()` | `DELETE /deployment-zones/{deploymentZoneSlug}` |
| `client.entitlement_groups.list()` | `GET /entitlement-groups` |
| `client.entitlement_groups.get()` | `GET /entitlement-groups/{entitlementGroupSlug}` |
| `client.entitlement_groups.create()` | `POST /entitlement-groups` |
| `client.entitlement_groups.update()` | `PUT /entitlement-groups/{entitlementGroupSlug}` |
| `client.entitlement_groups.delete()` | `DELETE /entitlement-groups/{entitlementGroupSlug}` |
| `client.entitlement_groups.add_entitlement()` | `POST /entitlement-groups/{entitlementGroupSlug}/entitlements` |
| `client.entitlement_groups.remove_entitlement()` | `DELETE /entitlement-groups/{entitlementGroupSlug}/entitlements/{entitlementSlug}` |
| `client.entitlement_groups.get_usage()` | `GET /entitlement-groups/{entitlementGroupSlug}/usage` |
| `client.entitlements.list()` | `GET /entitlements` |
| `client.entitlements.get()` | `GET /entitlements/{entitlementSlug}` |
| `client.entitlements.create()` | `POST /entitlements` |
| `client.entitlements.update()` | `PUT /entitlements/{entitlementSlug}` |
| `client.entitlements.delete()` | `DELETE /entitlements/{entitlementSlug}` |

</details>

<details>
<summary><b>client.feature_flags</b> · <b>client.flags</b></summary>

| Method | Operation |
| --- | --- |
| `client.feature_flags.list()` | `GET /feature-flags` |
| `client.feature_flags.get()` | `GET /feature-flags/{featureFlagSlug}` |
| `client.feature_flags.create()` | `POST /feature-flags` |
| `client.feature_flags.update()` | `PUT /feature-flags/{featureFlagSlug}` |
| `client.feature_flags.delete()` | `DELETE /feature-flags/{featureFlagSlug}` |
| `client.feature_flags.manifest()` | `GET /openfeature/v0/manifest` |

</details>

<details>
<summary><b>client.instances</b> · <b>client.integrations</b></summary>

| Method | Operation |
| --- | --- |
| `client.instances.list()` | `GET /instances` |
| `client.instances.get()` | `GET /instances/{instanceSlug}` |
| `client.instances.create()` | `POST /instances` |
| `client.instances.update()` | `PUT /instances/{instanceSlug}` |
| `client.instances.update_status()` | `PATCH /instances/{instanceSlug}` |
| `client.instances.update_lifecycle_stage()` | `PATCH /instances/{instanceSlug}` |
| `client.instances.delete()` | `DELETE /instances/{instanceSlug}` |
| `client.instances.list_audit_trails()` | `GET /instances/{instanceSlug}/audit-trails` |
| `client.instances.list_usage()` | `GET /instances/{instanceSlug}/entitlements/usage` |
| `client.instances.get_usage()` | `GET /instances/{instanceSlug}/entitlements/{entitlementSlug}/usage` |
| `client.instances.report_usage()` | `POST /instances/{instanceSlug}/entitlements/{entitlementSlug}/usage` |
| `client.instances.get_integration()` | `GET /instances/{instanceSlug}/integrations/{integrationName}` |
| `client.instances.create_integration()` | `POST /instances/{instanceSlug}/integrations/{integrationName}` |
| `client.instances.update_integration()` | `PUT /instances/{instanceSlug}/integrations/{integrationName}` |
| `client.instances.delete_integration()` | `DELETE /instances/{instanceSlug}/integrations/{integrationName}` |
| `client.integrations.get_customer()` | `GET /integration/{adapter}/customer/{externalId}` |
| `client.integrations.upsert_customer()` | `PATCH /integration/{adapter}/customer/{externalId}` |
| `client.integrations.get_instance()` | `GET /integration/{adapter}/instance/{externalId}` |
| `client.integrations.upsert_instance()` | `PATCH /integration/{adapter}/instance/{externalId}` |

</details>

<details>
<summary><b>client.licenses</b> · <b>client.metadata_fields</b></summary>

| Method | Operation |
| --- | --- |
| `client.license_families.list()` | `GET /license-families` |
| `client.license_families.get()` | `GET /license-families/{familySlug}` |
| `client.licenses.list()` | `GET /licenses` |
| `client.licenses.get()` | `GET /licenses/{licenseSlug}` |
| `client.licenses.create()` | `POST /licenses` |
| `client.licenses.update()` | `PUT /licenses/{licenseSlug}` |
| `client.licenses.delete()` | `DELETE /licenses/{licenseSlug}` |
| `client.licenses.publish()` | `POST /licenses/{licenseSlug}/publish` |
| `client.licenses.archive()` | `POST /licenses/{licenseSlug}/archive` |
| `client.licenses.unarchive()` | `POST /licenses/{licenseSlug}/unarchive` |
| `client.licenses.list_entitlements()` | `GET /licenses/{licenseSlug}/entitlements` |
| `client.licenses.get_entitlement()` | `GET /licenses/{licenseSlug}/entitlements/{entitlementSlug}` |
| `client.licenses.associate_entitlement()` | `POST /licenses/{licenseSlug}/entitlements` |
| `client.licenses.update_entitlement()` | `PUT /licenses/{licenseSlug}/entitlements/{entitlementSlug}` |
| `client.licenses.delete_entitlement()` | `DELETE /licenses/{licenseSlug}/entitlements/{entitlementSlug}` |
| `client.metadata_fields.list()` | `GET /metadata-fields` |
| `client.metadata_fields.create()` | `POST /metadata-fields` |
| `client.metadata_fields.update()` | `PATCH /metadata-fields/{id}` |
| `client.metadata_fields.archive()` | `POST /metadata-fields/{id}/archive` |
| `client.metadata_fields.unarchive()` | `POST /metadata-fields/{id}/unarchive` |
| `client.metadata_fields.dry_run()` | `POST /metadata-fields/{id}/dry-run` |
| `client.metadata_fields.reorder()` | `POST /metadata-fields/reorder` |

</details>

<details>
<summary><b>client.releases</b> · <b>client.service_accounts</b></summary>

| Method | Operation |
| --- | --- |
| `client.releases.list()` | `GET /releases` |
| `client.releases.get()` | `GET /releases/{releaseSlug}` |
| `client.releases.create()` | `POST /releases` |
| `client.releases.delete()` | `DELETE /releases/{releaseSlug}` |
| `client.service_accounts.list()` | `GET /service-accounts` |
| `client.service_accounts.get()` | `GET /service-accounts/{serviceAccountSlug}` |
| `client.service_accounts.create()` | `POST /service-accounts` |
| `client.service_accounts.update()` | `PUT /service-accounts/{serviceAccountSlug}` |
| `client.service_accounts.list_tokens()` | `GET /service-accounts/{serviceAccountSlug}/tokens` |
| `client.service_accounts.create_token()` | `POST /service-accounts/{serviceAccountSlug}/tokens` |
| `client.service_accounts.delete_token()` | `DELETE /service-accounts/{serviceAccountSlug}/tokens/{tokenSlug}` |

</details>

<details>
<summary><b>Platform API</b> — <code>KaitenPlatformClient</code></summary>

| Method | Operation |
| --- | --- |
| `platform.me()` | `GET /platform/me` |
| `platform.connectors.register()` | `POST /platform/connectors` |
| `platform.organizations.ensure()` | `POST /platform/organizations` |
| `platform.organizations.get()` | `GET /platform/organizations/{orgId}` |
| `platform.organizations.delete()` | `DELETE /platform/organizations/{orgId}` |
| `platform.organizations.delete_membership()` | `DELETE /platform/organizations/{orgId}/memberships/{userId}` |
| `platform.tokens.mint()` | `POST /platform/organizations/{orgId}/tokens` |
| `platform.tokens.list()` | `GET /platform/organizations/{orgId}/tokens` |
| `platform.tokens.revoke()` | `DELETE /platform/organizations/{orgId}/tokens/{tokenSlug}` |
| `platform.users.delete()` | `DELETE /platform/users/{id}` |

</details>

## How the SDK stays true to the API

An SDK written by hand drifts from the API it wraps, one renamed field at a time — and a request
body with one key too many is refused on every call. This one is built so that it cannot drift
silently:

1. **The contract is vendored.** [`openapi/`](openapi/) holds a snapshot of Kaiten's two OpenAPI
   documents, copied from [kaitencloud/kaiten](https://github.com/kaitencloud/kaiten) by
   `task sync:openapi`, with the exact commit recorded in `openapi/source.yaml`.
2. **Models are generated from it**, by `scripts/generate_models.py`.
3. **Every operation is accounted for.** `openapi/coverage.yaml` maps each operation to the
   method that calls it; the tests fail when an operation is left unwrapped or a method maps to
   nothing.
4. **Every method is tested against the contract.** Each one is called against a fake API that
   answers like the contract says, and every request body it sends is validated against the
   operation's JSON Schema — once with all arguments, once with only the required ones.
5. **One implementation, two clients.** The sync client is generated from the async source by
   `scripts/unasync.py`, and the tests check both have the same signatures.

CI checks all of it on every change, on Python 3.10 to 3.14 and on the oldest supported
versions of the dependencies.

## Development

The workflows are [Task](https://taskfile.dev) targets over [uv](https://docs.astral.sh/uv/):

```bash
task setup      # install the development environment
task check      # everything CI runs
```

| Task | What it does |
| --- | --- |
| `task test` | Run the test suite with coverage |
| `task lint` / `task fmt` | Check or fix linting and formatting (ruff) |
| `task typecheck` | `mypy --strict` over the package |
| `task generate` | Regenerate the models and the sync client |
| `task sync:openapi` | Copy the contract from a kaiten checkout (`KAITEN_PATH`, default `../kaiten`), then regenerate |
| `task build` | Build the sdist and the wheel, and check their metadata |

[The playbook](#the-playbook) is part of the test suite: every step runs against the fake API,
so a renamed method or an argument the contract no longer accepts fails in CI rather than
halfway through somebody's walkthrough.

Never edit `src/kaitencloud/_sync/` or the generated `src/kaitencloud/types/` modules by hand:
change the async source, the contract or a generator, then run `task generate`.

Contributions are welcome — [CONTRIBUTING.md](CONTRIBUTING.md) says how, and every commit carries
a [DCO](DCO.md) sign-off (`git commit -s`). Report a vulnerability privately, as
[SECURITY.md](SECURITY.md) describes, never in a public issue.

## Versioning

The SDK follows [Semantic Versioning](https://semver.org): only a major release changes the
public API — the [changelog](CHANGELOG.md) says how — while a minor release adds to it and a
patch release fixes it.

## License

Kaiten SDK for Python is open source and licensed under the
[Apache License, Version 2.0](./LICENSE).

By contributing, you agree to certify your contribution under the
[Developer Certificate of Origin 1.1](./DCO.md).

The Kaiten name and logos are not licensed under Apache-2.0.
See the Kaiten trademark policy in the main Kaiten repository.
