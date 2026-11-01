# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html): only a major version changes the
public API, a minor version adds to it, and a patch version fixes it.

## [1.1.0] - 2026-11-01

Generated and tested against the contract of Kaiten 26.10.8,
[`kaitencloud/kaiten@f685ceb8`](https://github.com/kaitencloud/kaiten/commit/f685ceb86bfeb5f6110663662fb955336ce1a1a4):
use it with Kaiten 26.10.8 or later. Nothing 1.0.0 published was removed or renamed: methods
only gained optional arguments.

### Added

- `client.billing`, a namespace per billing resource: the organization's settings, capabilities,
  health, provider sync and period close; `subscriptions` -- subscribe, change the provider and
  terms, cancel, reactivate, schedule and drop a plan change, the upcoming invoice, an instance's
  invoices; `invoices` -- list, export, void, recompose, mark paid, write off, release a hold,
  retry a push, sync, and a line's usage reports; the accounting `handoff`, claimed and
  acknowledged; `license_prices` and the invoice preview; `addons`, with their families, grants,
  prices and the license families they fit; `instance_addons`; `vouchers`, their redemptions and
  lookup, and `instance_vouchers`; `customers` -- a customer's billing, payment method and
  provider portal; `publishable_keys`, `customer_sessions` and `checkout_sessions`.
- `client.billing.public` and `client.billing.session`: what a publishable key (`pk_...`), an
  anonymous checkout's token (`ksc_...`) and a customer session (`kst_...`) reach. A route under
  `/public` takes one of them and refuses any other; the SDK refuses the mix-up before sending,
  and sends a publishable key in `X-Kaiten-Publishable-Key`, never as a bearer token.
- `instances.report_usage_detailed()`: a usage report under an idempotency key,
  `transaction_id`, which Kaiten applies at most once. It returns a `UsageReportResult`: the
  usage, whether the report was a replay, and whether its metadata was too large to store. A key
  spent on another report raises `TransactionIdReusedError`.
- The usage history: `instances.list_usage_reports()`, `instances.export_usage_reports()` and
  `instances.export_organization_usage_reports()`.
- Entitlement exceptions: `instances.list_entitlement_exceptions()`,
  `instances.create_entitlement_exception()` and `instances.revoke_entitlement_exception()`.
- `license_families.update()`: whether a family is public, its fallback family, and how its
  trials end.
- A license version's commercial terms on `licenses.create()` and `licenses.update()`:
  `pricing_type`, `trial_period_days`, `requires_payment_method` and `self_serve_cta_url`. A
  customer's `billing_email` on `customers.create()` and `customers.update()`.
  `metadata_fields.list(include_archived=True)`.
- `platform.billing.close_periods()`, the Platform API's eleventh operation.
- Models for every new response, and for the 62 webhook events published since 1.0.0: all 117
  are typed. An event carries the delivery's trace `headers`, and its `data` who wrote the change
  (`via`, `checkout_session_id`, `customer_session_id`); that `data` is still an instance of the
  class 1.0.0 typed it with.
- `feature_flags.targeting_context()`, `feature_flags.lint_rule()` and `feature_flags.test_rule()`:
  the facts a targeting rule can read, the check the API runs before accepting one, and a dry run
  of a rule against a customer or an instance.
- `feature_flags.update(..., slug=...)` renames a flag.

### Changed

- The models require what Kaiten 26.10.8 always sends and older deployments do not:
  `EntitlementUsage.source`, `AuditTrail.actor`, `ConnectorSettings.configured`, the trial and
  catalog settings of `LicenseFamilyView`, and the period rollover event's `reason`. From an older
  Kaiten, those reads raise `APIResponseValidationError`, and that event `WebhookPayloadError`.
- `ResetAnchor` gains `BILLING_PERIOD`, and `Scope` the `read:` and `write:` scopes of `addons`,
  `billing`, `customer_sessions`, `profile`, `publishable_keys`, `users`, `voucher_redemptions` and
  `vouchers`.

### Fixed

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

[1.1.0]: https://github.com/kaitencloud/sdk-python/releases/tag/v1.1.0
[1.0.0]: https://github.com/kaitencloud/sdk-python/releases/tag/v1.0.0
