# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""A fake Kaiten answering AI usage reports, for the metering and wrapper tests.

It answers each reservation and commit the way the API does -- 200, with the outcome echoing
the transaction id -- unless a test scripted a refusal for that phase. It never sees a prompt
or a completion, and neither do the tests: every usage in them is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

USAGE = {
    "entitlementId": "e1",
    "entitlementSlug": "chat-credits",
    "licenseId": "l1",
    "licenseSlug": "pro-v3",
    "value": {"type": "number", "value": 90},
    "limit": {"type": "number", "value": 100},
}

Answer = Callable[[httpx.Request], httpx.Response]


def problem(status: int, code: str | None, detail: str = "refused") -> Answer:
    payload: dict[str, Any] = {"title": "Refused", "status": status, "detail": detail}
    if code is not None:
        payload["code"] = f"ReportEntitlementUsageMetric.{code}"
    return lambda request: httpx.Response(status, json=payload)


def status(code: int) -> Answer:
    return lambda request: httpx.Response(code, json={"title": "Unavailable", "detail": "down"})


def network_error(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadError("connection reset", request=request)


@dataclass
class Report:
    """One AI usage report the fake received."""

    value: dict[str, Any]
    body: dict[str, Any]
    request: httpx.Request

    @property
    def phase(self) -> str:
        return str(self.value["phase"])

    @property
    def transaction_id(self) -> str:
        return str(self.value["transactionId"])

    @property
    def key(self) -> str | None:
        return self.request.headers.get("idempotency-key")


@dataclass
class FakeKaiten:
    """Every AI report received, in order; ``script`` queues answers per phase."""

    reports: list[Report] = field(default_factory=list)
    script: dict[str, list[Answer]] = field(default_factory=dict)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        value = body["value"]
        assert value["type"] == "ai_usage", value
        self.reports.append(Report(value, body, request))
        queued = self.script.get(value["phase"])
        if queued:
            return queued.pop(0)(request)
        outcome = {
            "transactionId": value["transactionId"],
            "phase": value["phase"],
            "status": "RESERVED" if value["phase"] == "reserve" else "COMMITTED",
            "credits": {"reserved": "6.6"}
            if value["phase"] == "reserve"
            else {"reserved": "6.6", "computed": "1.2", "charged": "1.2"},
            "remaining": "3.4",
            "warnings": [],
        }
        return httpx.Response(200, json={**USAGE, "reserved": "6.6", "ai": outcome})

    def refuse(self, phase: str, *answers: Answer) -> None:
        self.script.setdefault(phase, []).extend(answers)

    @property
    def phases(self) -> list[tuple[str, str]]:
        """(phase, transaction id) of every report: each retry appears once more."""
        return [(report.phase, report.transaction_id) for report in self.reports]

    @property
    def commits(self) -> list[dict[str, Any]]:
        return [report.value for report in self.reports if report.phase == "commit"]

    @property
    def reserves(self) -> list[dict[str, Any]]:
        return [report.value for report in self.reports if report.phase == "reserve"]
