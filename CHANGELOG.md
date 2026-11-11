# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html): only a major version changes the
public API, a minor version adds to it, and a patch version fixes it.

## [Unreleased]

### Added

- Explainable AI charges (preview; requires a Kaiten release with explainable AI charges,
  version to be set): `commit_ai_usage(..., vendor_cost=...)`, sent exactly as spelled;
  `ai.rule` on report answers; inference rows with their pricing snapshot, license, warnings,
  report sequence, vendor cost and refunds; history filters `authorized`, `model_slug`,
  `model`, `request_type`; `instances.list_organization_ai_inferences()`;
  `instances.refund_ai_inference()` under a generated, retried `Idempotency-Key`, with one
  error class per refusal; `instances.get_ai_capabilities()`; `ai.release()`; the known
  warnings in `ai.AI_WARNINGS`, `NO_RESERVATION` and `COUNTER_PRECISION_DEGRADED` included.
- `vendor_cost=` and `on_commit_failure=` on `ai.run`, the meters, the OpenAI and Anthropic
  drop-ins and `wrap_openai` / `wrap_anthropic`.
- `AiUsageDisabledError` for 403 `AIUsage.Disabled`, and `AiCommitFailedError`.

- Regenerated the AI credits contract, including write-only `ReportUsageValue`,
  typed usage outcomes/gauges and model/conversion-rule events. Original AI
  response bridge names now alias generated models.
- Model catalogue CRUD, license conversion-rule management, paged inference
  history and open reservation reads on both clients.

- Optional OpenAI and Anthropic drop-in clients and existing-client wrappers, with
  allow-listed reserve/call/commit accounting, sync/async streaming settlement,
  pluggable estimates and provider timeout-based reservation lifetimes.
- Documented current agent SDK accounting interfaces and the missing supported
  per-model-inference gating boundary; no misleading run-budget wrappers.

- `feature_flags.targeting_context()`, `feature_flags.lint_rule()` and `feature_flags.test_rule()`:
  the facts a targeting rule can read, the check the API runs before accepting one, and a dry run
  of a rule against a customer or an instance.
- `feature_flags.update(..., slug=...)` renames a flag.

### Changed

- AI metering fails closed. An entitlement that is not an AI credit pool, or a deployment
  without AI credits, raises `AiUsageUnsupportedError` on every call instead of disabling
  metering for the rest of the process; a deployment without AI credits is detected through
  `GET /ai/capabilities`, not guessed from a 422.
- A commit that fails after its retries raises `AiCommitFailedError` instead of being logged
  and dropped, unless `on_commit_failure=` is given.
- AI report answers are `ReportedEntitlementUsage`, the shape every usage report answers with.

- Unreleased AI helpers, meters and provider wrappers select the AI credit entitlement
  with `entitlement=` rather than `pool=`; the old keyword is not accepted.
  Low-level instance methods still use `entitlement_slug`, and HTTP routes are unchanged.

### Fixed

- A metered call whose task is cancelled, or interrupted, is committed (`CUSTOMER_ERROR`)
  before the cancellation propagates, and an async commit completes even when its task is
  cancelled.
- A provider stream closed before its first event is settled `CUSTOMER_ERROR`, not released
  as `NOT_SENT`: the request was sent.

- `feature_flags.update` sends the flag's slug. Without it, Kaiten blanked the slug and the flag
  could no longer be reached.

## [1.0.0] - 2026-10-01

The first release of the Kaiten Python SDK, generated and tested against the contract of
[`kaitencloud/kaiten@fa7f554f`](https://github.com/kaitencloud/kaiten/commit/fa7f554fb6464f52c2a3f1ed487f4c7383c8125d).

### Added

- `KaitenClient` and `AsyncKaitenClient` for the Core API: customers, instances, licenses and
  license families, entitlements and entitlement groups, usage reporting, feature flag
  definitions, deployment zones, releases, components, metadata fields, service accounts,
  connectors and integrations -- 98 of the contract's 107 operations. Of the nine left out,
  three are the console's rule-editor tooling and four a signed-in person's notification feed
  and preferences, which Kaiten's own SDK coverage excludes too; the other two are OFREP flag
  evaluation, which belongs to OpenFeature (see below).
- `KaitenPlatformClient` and `AsyncKaitenPlatformClient` for the Platform API: all 10 operations.
- Configuration from arguments or from `KAITEN_BASE_URL` and `KAITEN_AUTH_TOKEN`. There is no
  default API address: every deployment has its own, and the SDK never guesses where to send
  a token.
- License versioning: `licenses.create()` opens a license family or adds its next version
  (`family_slug`, `family_id`, `lifecycle_state`), `licenses.publish()`, `archive()` and
  `unarchive()` move a version through its lifecycle, and `license_families.list()` and
  `get()` resolve a family to the version it currently serves, or to a pinned one.
- Models for every response and every webhook event, generated from the contract with
  pydantic v2: snake_case attributes, lenient about fields and enum values added after a
  release, and `to_dict()` for the exact wire shape.
- `kaitencloud.types.Scope`, every scope an organization token can carry, generated from the
  contract and used to type `service_accounts.create_token()` and `platform.tokens.mint()`.
- List methods that walk every page, and fail with `PaginationError` rather than return a list
  the API said was incomplete.
- Automatic retries with exponential backoff for requests that are safe to repeat -- never a
  usage report -- honouring `Retry-After`.
- Typed errors for every failure, carrying the RFC 9457 problem: `code`, `detail`, `error_id`.
  `ThresholdExceededError` for a usage report refused at the license's cap.
- A credential guard that refuses a platform credential on the Core client, an organization
  token on the platform client, and a webhook secret on either, before anything is sent.
- `kaitencloud.webhooks`: Svix signature verification, and a typed model for each of the 55
  published events.
- `kaitencloud.targeting`, builders for feature flag variants, rollouts and targeting rules.
- `kaitencloud.usage`, the enforcement arithmetic the API applies to a grant and its overage
  allowance.
- `examples/playbook.py`, a resumable walk through a deployment of your own, step by step.

### Not included, on purpose

- Flag evaluation. Kaiten implements OFREP, so flags are evaluated with an OpenFeature SDK and
  its generic OFREP provider (`openfeature-provider-ofrep`); the README shows how.

[1.0.0]: https://github.com/kaitencloud/sdk-python/releases/tag/v1.0.0
