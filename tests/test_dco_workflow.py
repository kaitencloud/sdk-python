# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The DCO workflow: every commit of a pull request is signed off by its author.

The check lives inside ``.github/workflows/dco.yml`` so the workflow is one file any repository
can copy. These tests run that very code, extracted from the workflow, rather than a copy of it.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml
from contract import ROOT

WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "dco.yml").read_text(encoding="utf-8"))


def _check() -> dict[str, Any]:
    (step,) = [step for step in WORKFLOW["jobs"]["dco"]["steps"] if step.get("shell") == "python"]
    namespace: dict[str, Any] = {"__name__": "dco_check"}  # anything but __main__: no API call
    exec(compile(step["run"], "dco.yml", "exec"), namespace)  # the repository's own code
    return namespace


check = _check()
JANE = {"name": "Jane Doe", "email": "jane@example.com"}


def commit(
    message: str,
    *,
    author: dict[str, str] = JANE,
    committer: dict[str, str] = JANE,
    parents: int = 1,
    account: str = "User",
) -> dict[str, Any]:
    """A commit as GET /repos/{owner}/{repo}/pulls/{number}/commits lists it."""
    return {
        "sha": "0123456789abcdef0123456789abcdef01234567",
        "parents": [{"sha": f"p{n}"} for n in range(parents)],
        "author": {"login": "jane", "type": account},
        "commit": {"message": message, "author": author, "committer": committer},
    }


def test_the_workflow_runs_from_main_with_read_only_access() -> None:
    # `on` is YAML 1.1's spelling of true, so PyYAML reads the key as a boolean.
    triggers = WORKFLOW.get("on", WORKFLOW.get(True))
    assert set(triggers) == {"pull_request_target"}  # main's version judges, not the PR's
    assert WORKFLOW["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert WORKFLOW["jobs"]["dco"]["name"] == "DCO"  # the check a ruleset requires
    uses = [step.get("uses", "") for step in WORKFLOW["jobs"]["dco"]["steps"]]
    assert not any(uses), "the pull request's code is never checked out"


@pytest.mark.parametrize(
    "message",
    [
        "feat: a change\n\nSigned-off-by: Jane Doe <jane@example.com>",
        "feat: a change\n\nSigned-off-by: jane doe <JANE@example.com>",  # case is not identity
        "feat: a change\n\nSigned-off-by: Someone Else <else@example.com>\n"
        "Signed-off-by: Jane Doe <jane@example.com>",  # the author's among several is enough
        "feat: a change\n\nSigned-off-by: Jane Doe <jane@example.com>  \n",  # trailing spaces
    ],
)
def test_a_commit_signed_off_by_its_author_passes(message: str) -> None:
    assert check["problem"](commit(message)) is None


def test_a_commit_without_a_sign_off_fails_and_says_what_was_expected() -> None:
    why = check["problem"](commit("feat: a change"))
    assert why is not None
    assert "no Signed-off-by" in why
    assert "Jane Doe <jane@example.com>" in why


@pytest.mark.parametrize(
    "signoff",
    [
        "Signed-off-by: Jane Doe <jane@elsewhere.com>",  # the right name, another address
        "Signed-off-by: J. Doe <jane@example.com>",  # the right address, another name
        "Signed-off-by: Someone Else <else@example.com>",  # somebody else entirely
    ],
)
def test_a_sign_off_by_anyone_but_the_author_fails(signoff: str) -> None:
    why = check["problem"](commit(f"feat: a change\n\n{signoff}"))
    assert why is not None
    assert "not by its author" in why


def test_the_committer_cannot_sign_off_for_the_author() -> None:
    applied = commit(
        "fix: a change\n\nSigned-off-by: Max Mustermann <max@example.com>",
        committer={"name": "Max Mustermann", "email": "max@example.com"},
    )
    assert check["problem"](applied) is not None


def test_a_sign_off_must_be_a_trailer_line_not_a_mention() -> None:
    quoted = "docs: explain the DCO\n\nWrite `Signed-off-by: Jane Doe <jane@example.com>` in yours."
    assert check["problem"](commit(quoted)) is not None


def test_a_merge_commit_is_not_checked() -> None:
    assert check["problem"](commit("Merge branch 'main'", parents=2)) is None


def test_a_bot_account_is_not_checked() -> None:
    bump = commit(
        "build(deps): bump httpx",
        author={"name": "dependabot[bot]", "email": "support@github.com"},
        account="Bot",
    )
    assert check["problem"](bump) is None
