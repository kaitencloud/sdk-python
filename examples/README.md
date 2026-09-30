# The playbook

[`playbook.py`](playbook.py) is a guided tour of a Kaiten deployment: one script that walks the
API from end to end against a deployment of your own. It builds a catalog, a license, a customer
and an instance, meters usage until the license refuses a report, evaluates a feature flag, mints
and revokes a token, verifies a webhook signature — then deletes everything it made.

Every step prints the call it is about to make before making it, so the script reads as
documentation that runs, and a failure points at the one call that failed.

> **It writes real data** into the organization its token belongs to. Point it at a development
> deployment, not at production.

## Before you start

Run it from the repository root, with a credential that may write:

```bash
export KAITEN_BASE_URL=http://localhost:6000
export KAITEN_AUTH_TOKEN=ksh_...   # an organization token
```

The `flags` step evaluates through OpenFeature, since [the SDK does not evaluate flags
itself](../README.md#feature-flags) — Kaiten speaks OFREP, so the generic provider does the
evaluating:

```bash
uv pip install openfeature-sdk openfeature-provider-ofrep
```

Without it, that step says so and moves on. Everything else runs on the SDK alone.

## The steps

```bash
uv run python examples/playbook.py --list
```

```text
  1. connect  Read every collection, and see what the credential may do
  2. catalog  An entitlement group, and the entitlements it holds
  3. license  A license, the values it grants, and a second version of it
  4. customer  A customer, and its link to a CRM
  5. product  A component, a release, and the zone it is deployed to
  6. metadata  A typed metadata field instances must satisfy
  7. instance  An instance of your product, for that customer
  8. usage  Meter usage, until the license refuses a report
  9. flags  A feature flag, defined here and evaluated through OpenFeature
 10. tokens  A service account, and a token that works until it is revoked
 11. webhooks  Verify a delivery, with nothing on the network
 12. platform  The Platform API, if a ksm_ credential is configured
 13. cleanup  Delete everything this run created
```

They build on each other: the license grants what the catalog defined, the instance belongs to
the customer and to that license, and the usage step meters against the instance. Run them in
order the first time.

The `license` step also drafts a second version of the license in the same family, then walks it
through its lifecycle — published, archived, put back on sale — reading the family after each
move to show which version it serves. The instance stays on version 1 throughout.

## Taking it slowly

`--pause` stops before each step and waits for Enter, which is how to read it the first time:

```bash
uv run python examples/playbook.py --pause
```

Stop whenever you like. A later session picks up where you left off, because the run remembers
what it created:

```bash
uv run python examples/playbook.py --from usage
```

Or run just the steps you care about, against what the earlier ones left behind:

```bash
uv run python examples/playbook.py flags tokens
```

Then hand it all back:

```bash
uv run python examples/playbook.py cleanup
```

## What a run leaves behind

Every resource is named after the run — `playbook-a1b2-acme`, `playbook-a1b2-seats` — and every
one of them is recorded in `.kaiten-playbook.json` as it is created. That file is what makes
`--from` possible, and it is what `cleanup` reads: **cleanup deletes only what that file
records**, never a resource it did not create. It is also never included by accident — neither a
bare run nor `--from` runs it — so you have to ask for it.

Two things cannot be deleted, and the playbook says so rather than pretend otherwise: a metadata
field is archived (which frees its key), and a service account has no delete endpoint, so it
stays behind with no live token.

Running the playbook twice gives two runs with two prefixes, which do not collide. Delete the
state file to start fresh.

## Options

| Option | What it does |
| --- | --- |
| `--list` | Print the steps and exit — the one invocation that needs no credential |
| `--pause` | Wait for Enter before each step |
| `--from STEP` | Resume at a step and run to the end |
| `STEP [STEP ...]` | Run only these steps |
| `--base-url`, `--token` | Instead of `KAITEN_BASE_URL` and `KAITEN_AUTH_TOKEN` |
| `--platform-org UUID` | The organization the `platform` step mints a token in |
| `--state PATH` | Where the run is recorded (default `.kaiten-playbook.json`) |
| `--verbose` | Log retries and fallbacks on the `kaitencloud` logger |

The `platform` step skips itself unless `KAITEN_PLATFORM_BASE_URL` and `KAITEN_PLATFORM_TOKEN`
are set: the Platform API has its own listener, reachable only from inside your infrastructure.

## How it is kept honest

`tests/test_playbook.py` runs every step against the same contract-backed fake the rest of the
suite uses, and `mypy --strict` covers this directory. So a method renamed in the SDK, or an
argument the contract no longer accepts, fails in CI rather than halfway through your
walkthrough — which is how the flag step's OpenFeature wiring and a typing defect in
`kaitencloud.targeting` were both caught.
