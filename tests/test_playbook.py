# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The example playbook runs, end to end, against a fake API built from the contract.

``examples/playbook.py`` is a script people run against their own deployment, so it is kept
honest the same way the README is: every step is executed here against the contract's own
shapes, with nothing on the network. A method renamed in the SDK, or an argument the contract
no longer accepts, fails here rather than halfway through somebody's walkthrough.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
import requests
from contract import ROOT, contract_api, find_operation, sample
from helpers import BASE_URL, ORG_ID, PLATFORM_URL, Recorder, recording

from kaitencloud import KaitenClient, KaitenPlatformClient


def _load() -> Any:
    path = ROOT / "examples" / "playbook.py"
    spec = importlib.util.spec_from_file_location("playbook", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["playbook"] = module
    spec.loader.exec_module(module)
    return module


playbook = _load()


@pytest.fixture(autouse=True)
def ofrep(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    """The OpenFeature provider's own HTTP calls, answered from the contract.

    The playbook evaluates flags through ``openfeature-provider-ofrep``, which sends them with
    ``requests`` rather than the SDK's httpx client -- so the fake transport the rest of these
    tests use never sees them. This answers them the way the contract does, and records where
    the provider went, which is what pins the base URL convention down.
    """
    calls: list[tuple[str, Any]] = []

    def post(_session: requests.Session, url: str, **kwargs: Any) -> requests.Response:
        calls.append((url, kwargs))
        _, schema = find_operation("core", "POST", "/api/ofrep/v1/evaluate/flags/a-flag").success()
        body = sample(schema, "core")
        body["value"] = True  # OFREP types `value` as any: the flag's own type decides
        response = requests.Response()
        response.status_code = 200
        response.headers["content-type"] = "application/json"
        response._content = json.dumps(body).encode()
        return response

    monkeypatch.setattr(requests.Session, "post", post)
    return calls


@pytest.fixture
def book(tmp_path: Path) -> Any:
    """A playbook wired to fake APIs that answer the way the contract says."""

    def core(token: str = "ksh_playbook") -> KaitenClient:
        transport = recording(contract_api("core"), Recorder())
        return KaitenClient(
            token=token, base_url=BASE_URL, http_client=httpx.Client(transport=transport)
        )

    platform = KaitenPlatformClient(
        token="ksm_playbook",
        base_url=PLATFORM_URL,
        http_client=httpx.Client(transport=recording(contract_api("platform"), Recorder())),
    )
    return playbook.Playbook(
        client=core(),
        state=playbook.State(tmp_path / "state.json"),
        platform=platform,
        platform_org=ORG_ID,
        client_factory=core,
        token="ksh_playbook",
    )


@pytest.mark.parametrize("step", playbook.STEPS, ids=lambda step: step.name)
def test_every_step_runs(step: Any, book: Any, capsys: pytest.CaptureFixture[str]) -> None:
    step.run(book)
    assert capsys.readouterr().out, f"{step.name} printed nothing"


def test_the_steps_run_in_order_and_leave_nothing_behind(
    book: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    for step in playbook.STEPS:
        step.run(book)

    output = capsys.readouterr().out
    assert "created" in output
    assert "deleted" in output  # the cleanup step ran
    assert not book.state.path.exists()  # and cleared the state file


def test_flags_are_evaluated_through_openfeature(
    book: Any, ofrep: list[tuple[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    """The SDK defines the flag; the OpenFeature provider is what reads it back."""
    step = next(step for step in playbook.STEPS if step.name == "flags")
    step.run(book)

    assert ofrep, "the playbook never evaluated a flag through OpenFeature"
    for url, kwargs in ofrep:
        assert "/api/ofrep/v1/evaluate/flags/" in url  # the provider appends this to base_url
        assert kwargs["headers"] == {"Authorization": "Bearer ksh_playbook"}
        assert kwargs["json"]["context"]["targetingKey"].endswith("-acme")

    output = capsys.readouterr().out
    assert "OFREPProvider" in output
    assert "client.flags" not in output  # the SDK has no evaluation method, on purpose


def test_the_steps_are_named_once_and_start_and_end_where_expected() -> None:
    names = [step.name for step in playbook.STEPS]
    assert len(names) == len(set(names))
    assert names[0] == "connect"
    assert names[-1] == "cleanup"


def test_listing_the_steps_needs_no_credential(capsys: pytest.CaptureFixture[str]) -> None:
    assert playbook.main(["--list"]) == 0
    listed = capsys.readouterr().out
    assert all(step.name in listed for step in playbook.STEPS)


@pytest.mark.parametrize("argv", [["nope"], ["--from", "nope"]])
def test_an_unknown_step_is_refused(argv: list[str]) -> None:
    with pytest.raises(SystemExit, match="nope"):
        playbook.main(argv)


def test_a_selection_is_honoured() -> None:
    selected = playbook.chosen(playbook.parse(["catalog", "usage"]))
    assert [step.name for step in selected] == ["catalog", "usage"]

    resumed = playbook.chosen(playbook.parse(["--from", "flags"]))
    assert next(step.name for step in resumed) == "flags"
    assert "cleanup" not in [step.name for step in resumed]  # never by accident
