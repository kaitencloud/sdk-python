# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html): until 1.0.0, a minor version may
change the public API, and a patch version never does.

## [0.1.0] - Unreleased

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
