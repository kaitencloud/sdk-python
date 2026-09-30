# Contributing to Kaiten SDK for Python

Thank you for contributing to the Kaiten Python SDK.

This project is licensed under the Apache License, Version 2.0.

## Developer Certificate of Origin

Kaiten uses the Developer Certificate of Origin 1.1 (DCO) for contributions.

Every commit must include a `Signed-off-by` trailer matching the commit author.

Use:

```bash
git commit -s -m "Describe your change"
```

This produces:

```text
Signed-off-by: Jane Doe <jane@example.com>
```

The `-s` flag is a DCO sign-off. It is different from cryptographic commit
signing with `git commit -S`.

See [DCO.md](./DCO.md) for the full DCO text.

## Contribution rules

Please:

- keep pull requests focused;
- add or update tests when behavior changes;
- update documentation when relevant;
- do not include secrets, customer data, or confidential information;
- do not submit code or assets that you do not have the right to contribute;
- preserve required third-party license and attribution notices.

Accepted contributions are contributed under Apache-2.0.

## Before you open a pull request

The development workflows are [Task](https://taskfile.dev) targets over
[uv](https://docs.astral.sh/uv/); the README's
[Development](./README.md#development) section lists them all.

```bash
task setup   # install the development environment
task check   # everything CI runs
```

Every Python file opens with the project's license notice:

```python
# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0
```

The tests check it, generated files included. Never edit the generated
`src/kaitencloud/_sync/` or `src/kaitencloud/types/` modules by hand: change
the async source, the contract or a generator, then run `task generate`.

## Security

Do not report unpatched vulnerabilities in public issues.

See [SECURITY.md](./SECURITY.md).
