# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Explainable AI charges: vendor costs, the pricing rule, history, refunds, cancellation.

Also the compatibility promise both ways: a response from a Kaiten that predates these members
parses, and one carrying members a later Kaiten adds parses too.
"""

from __future__ import annotations

import asyncio
import copy
import json
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest
from ai_fakes import USAGE, FakeKaiten, network_error, status

from kaitencloud import (
    AiInferenceNotCommittedError,
    AiInferenceNotFoundError,
    AiPoolNotFoundError,
    AiPoolNotGrantedError,
    AiUsageDisabledError,
    AsyncKaitenClient,
    ConflictError,
    IdempotencyKeyReusedError,
    InvalidIdempotencyKeyError,
    InvalidRefundError,
    KaitenClient,
    NotFoundError,
    NothingToRefundError,
    RefundExceedsRefundableError,
    TransactionIdReusedError,
    UnprocessableEntityError,
    ai,
)
from kaitencloud.types import AiInference, AiUsageOutcome, ConversionRule, OrganizationAiInference

INSTANCE, POOL = "acme-prod", "chat-credits"
USER = {"id": "8a1f0e2b-1c3d-4e5f-9a7b-6c5d4e3f2a1b", "name": "Ada Lovelace"}

# An inference row as a Kaiten with AI credits but before explainable charges answers it.
OLD_ROW: dict[str, Any] = {
    "transactionId": "req-42",
    "status": "COMMITTED",
    "reportedAt": "2026-11-11T10:00:00Z",
    "committedAt": "2026-11-11T10:00:02Z",
    "model": "gpt-4o-2024-11-20",
    "modelSlug": "gpt-4o",
    "requestType": "COMPLETION",
    "requestStatus": "SUCCESS",
    "usage": {"inputTokens": 1000, "outputTokens": 800},
    "authorized": True,
    "conversionRuleId": "3a9b8c7d-0000-4000-8000-000000000001",
    "credits": {"reserved": "3.4", "computed": "3.4", "charged": "3.4"},
    "valueBefore": 10,
    "valueAfter": 13.4,
    "windowStart": "2026-11-01T00:00:00Z",
}

# The same row with every member explainable charges add.
NEW_ROW: dict[str, Any] = {
    **OLD_ROW,
    "credits": {"reserved": "3.4", "computed": "3.4", "charged": "3.4", "refunded": "1.5"},
    "pricing": {
        "ruleId": "3a9b8c7d-0000-4000-8000-000000000001",
        "specificity": "EXACT_TYPED",
        "rates": {"perInputToken": "0.001", "perOutputToken": "0.003"},
        "minimumCreditsPerRequest": "0",
        "maximumCreditsPerRequest": "50",
        "chargeOnError": "NEVER",
    },
    "licenseId": "6f1c2a9e-0000-4000-8000-000000000002",
    "licenseSlug": "pro",
    "warnings": ["MODEL_DEPRECATED"],
    "reportSeq": 17,
    "vendorCost": {"reported": "0.0125", "computed": "0.0122", "currency": "USD"},
    "refunds": [
        {
            "id": "8d0e0000-0000-4000-8000-000000000003",
            "credits": "1.5",
            "reason": "duplicate call",
            "reportSeq": 18,
            "createdAt": "2026-11-11T11:00:00Z",
            "createdBy": USER,
        }
    ],
}

OLD_RULE: dict[str, Any] = {
    "id": "3a9b8c7d-0000-4000-8000-000000000001",
    "licenseSlug": "pro",
    "entitlementSlug": POOL,
    "modelSlug": "gpt-4o",
    "requestType": "COMPLETION",
    "rates": {"perInputToken": "0.001"},
    "minimumCreditsPerRequest": "0",
    "maximumCreditsPerRequest": None,
    "chargeOnError": "NEVER",
    "status": "ACTIVE",
    "grantedByLicense": True,
    "createdAt": "2026-11-01T00:00:00Z",
    "updatedAt": "2026-11-01T00:00:00Z",
}
NEW_RULE: dict[str, Any] = {
    **OLD_RULE,
    "grantedByAddons": False,
    "createdBy": USER,
    "updatedBy": USER,
}


@pytest.fixture
def kaiten(make_client: Callable[..., Any]) -> tuple[KaitenClient, FakeKaiten]:
    fake = FakeKaiten()
    client, _ = make_client(fake)
    return client, fake


def problem(status_code: int, code: str, **extra: Any) -> httpx.Response:
    return httpx.Response(
        status_code, json={"title": "Refused", "detail": "refused", "code": code, **extra}
    )


# -- the vendor cost of a commit --------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "sent"),
    [
        ("0.0125", "0.0125"),
        ("0.010", "0.010"),
        (Decimal("0.010"), "0.010"),
        (Decimal("1E-12"), "0.000000000001"),
        (3, "3"),
        ("999999999999.123456789012", "999999999999.123456789012"),
    ],
)
def test_the_vendor_cost_is_sent_exactly_as_spelled(
    kaiten: tuple[KaitenClient, FakeKaiten], given: Any, sent: str
) -> None:
    client, fake = kaiten
    client.instances.commit_ai_usage(INSTANCE, POOL, transaction_id="t1", vendor_cost=given)
    assert fake.commits[0]["vendorCost"] == sent
    assert ai.vendor_cost_string(given) == sent


@pytest.mark.parametrize(
    "given",
    [
        0.01,
        True,
        "-0.01",
        "1e-3",
        " 0.01",
        "0.0000000000001",
        "1234567890123",
        Decimal("NaN"),
        Decimal("-1"),
    ],
)
def test_a_vendor_cost_the_api_would_refuse_is_refused_before_sending(
    kaiten: tuple[KaitenClient, FakeKaiten], given: Any
) -> None:
    client, fake = kaiten
    with pytest.raises(ValueError, match="vendor_cost"):
        client.instances.commit_ai_usage(INSTANCE, POOL, transaction_id="t1", vendor_cost=given)
    assert fake.reports == []


def test_a_release_takes_no_vendor_cost_and_a_reservation_has_none(
    kaiten: tuple[KaitenClient, FakeKaiten],
) -> None:
    client, fake = kaiten
    with pytest.raises(ValueError, match="NOT_SENT"):
        client.instances.commit_ai_usage(
            INSTANCE, POOL, transaction_id="t1", request_status="NOT_SENT", vendor_cost="0.01"
        )
    with pytest.raises(TypeError):
        client.instances.reserve_ai_usage(  # type: ignore[call-arg]
            INSTANCE, POOL, model="gpt-4o", vendor_cost="0.01"
        )
    assert fake.reports == []


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("failure", [status(503), network_error])
def test_a_retried_commit_resends_the_vendor_cost_byte_for_byte(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    asynchronous: bool,
    failure: Any,
) -> None:
    fake = FakeKaiten()
    fake.refuse("commit", failure, failure)

    async def scenario() -> None:
        client, _ = make_async_client(fake)
        async with client:
            await ai.commit(
                client,
                instance=INSTANCE,
                entitlement=POOL,
                transaction_id="t1",
                vendor_cost=Decimal("0.0100"),
            )

    if asynchronous:
        asyncio.run(scenario())
    else:
        client, _ = make_client(fake)
        ai.commit(
            client,
            instance=INSTANCE,
            entitlement=POOL,
            transaction_id="t1",
            vendor_cost=Decimal("0.0100"),
        )
    bodies = {report.request.content for report in fake.reports}
    assert len(fake.reports) == 3
    assert len(bodies) == 1, "every retry carries the same bytes"
    assert json.loads(bodies.pop())["value"]["vendorCost"] == "0.0100"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_run_commits_a_vendor_cost_read_out_of_the_result(
    make_client: Callable[..., Any], make_async_client: Callable[..., Any], asynchronous: bool
) -> None:
    fake = FakeKaiten()
    reply = {"usage": {"prompt_tokens": 10, "completion_tokens": 2}, "cost": "0.00042"}
    options: dict[str, Any] = {
        "instance": INSTANCE,
        "entitlement": POOL,
        "model": "gpt-4o",
        "usage": lambda result: ai.from_openai(result["usage"]),
        "vendor_cost": lambda result: result["cost"],
    }

    async def scenario() -> Any:
        client, _ = make_async_client(fake)
        async with client:

            async def call() -> Any:
                return reply

            return await ai.run(client, call, **options)

    if asynchronous:
        assert asyncio.run(scenario()) is reply
    else:
        client, _ = make_client(fake)
        assert ai.run(client, lambda: reply, **options) is reply
    assert fake.commits[0]["vendorCost"] == "0.00042"
    assert "vendorCost" not in fake.reserves[0]


def test_a_vendor_cost_function_that_fails_still_settles_the_call(
    kaiten: tuple[KaitenClient, FakeKaiten], caplog: pytest.LogCaptureFixture
) -> None:
    client, fake = kaiten

    def cost(result: Any) -> str:
        raise KeyError("cost")

    assert (
        ai.run(
            client,
            lambda: "reply",
            instance=INSTANCE,
            entitlement=POOL,
            model="m",
            vendor_cost=cost,
        )
        == "reply"
    )
    assert len(fake.commits) == 1
    assert "vendorCost" not in fake.commits[0]
    assert "attempting settlement without vendor cost" in caplog.text


# -- the answer: the rule, the warnings, the release ------------------------------------------


def test_an_answer_names_the_rule_that_priced_it(kaiten: tuple[KaitenClient, FakeKaiten]) -> None:
    client, fake = kaiten
    rule = {"id": "3a9b8c7d-0000-4000-8000-000000000001", "specificity": "ANY_TYPED"}

    def answer(request: httpx.Request) -> httpx.Response:
        value = json.loads(request.content)["value"]
        outcome = {
            "transactionId": value["transactionId"],
            "phase": "reserve",
            "status": "RESERVED",
            "credits": {"reserved": "6.6"},
            "remaining": "3.4",
            "rule": rule,
            "warnings": ["COUNTER_PRECISION_DEGRADED", "A_WARNING_FROM_A_LATER_KAITEN"],
        }
        return httpx.Response(200, json={**USAGE, "reserved": "6.6", "ai": outcome})

    fake.refuse("reserve", answer)
    reserved = client.instances.reserve_ai_usage(INSTANCE, POOL, model="gpt-4o")
    assert reserved.ai is not None
    assert reserved.ai.rule is not None
    assert (reserved.ai.rule.id, reserved.ai.rule.specificity) == (rule["id"], "ANY_TYPED")
    # Warnings are an open set: one this release does not know parses, and raises nothing.
    assert reserved.ai.warnings == ["COUNTER_PRECISION_DEGRADED", "A_WARNING_FROM_A_LATER_KAITEN"]
    assert "COUNTER_PRECISION_DEGRADED" in ai.AI_WARNINGS
    assert "A_WARNING_FROM_A_LATER_KAITEN" not in ai.AI_WARNINGS


@pytest.mark.parametrize("asynchronous", [False, True])
def test_a_release_without_a_reservation_says_so_and_closes_the_transaction(
    make_client: Callable[..., Any], make_async_client: Callable[..., Any], asynchronous: bool
) -> None:
    fake = FakeKaiten()
    fake.warnings = ["NO_RESERVATION"]

    def released(request: httpx.Request) -> httpx.Response:
        value = json.loads(request.content)["value"]
        outcome = {
            "transactionId": value["transactionId"],
            "phase": "commit",
            "status": "RELEASED",
            "credits": {},
            "remaining": "10",
            "warnings": ["NO_RESERVATION"],
        }
        return httpx.Response(200, json={**USAGE, "ai": outcome})

    late = problem(409, "ReportEntitlementUsageMetric.TransactionIdReused")
    fake.refuse("commit", released, lambda request: late)
    fake.refuse("reserve", lambda request: late)

    async def scenario() -> Any:
        client, _ = make_async_client(fake)
        async with client:
            answer = await ai.release(
                client, instance=INSTANCE, entitlement=POOL, transaction_id="t1"
            )
            with pytest.raises(TransactionIdReusedError):
                await ai.reserve(
                    client, instance=INSTANCE, entitlement=POOL, model="m", transaction_id="t1"
                )
            with pytest.raises(TransactionIdReusedError):
                await ai.commit(client, instance=INSTANCE, entitlement=POOL, transaction_id="t1")
            return answer

    if asynchronous:
        answer = asyncio.run(scenario())
    else:
        client, _ = make_client(fake)
        answer = ai.release(client, instance=INSTANCE, entitlement=POOL, transaction_id="t1")
        with pytest.raises(TransactionIdReusedError):
            ai.reserve(client, instance=INSTANCE, entitlement=POOL, model="m", transaction_id="t1")
        with pytest.raises(TransactionIdReusedError):
            ai.commit(client, instance=INSTANCE, entitlement=POOL, transaction_id="t1")
    assert answer.ai.status == "RELEASED"
    assert "NO_RESERVATION" in answer.ai.warnings
    assert fake.commits[0] == {
        "type": "ai_usage",
        "phase": "commit",
        "transactionId": "t1",
        "requestStatus": "NOT_SENT",
    }, "a release names no model: it needs none"


# -- reading inferences: both shapes -----------------------------------------------------------


def test_an_inference_row_from_before_explainable_charges_parses() -> None:
    row = AiInference.model_validate(OLD_ROW)
    assert row.warnings == []
    assert row.refunds == []
    assert row.pricing is None
    assert row.vendor_cost is None
    assert row.report_seq is None
    assert row.credits.refunded is None


def test_an_inference_row_says_what_was_charged_and_why() -> None:
    row = AiInference.model_validate(NEW_ROW)
    assert row.pricing is not None
    assert row.pricing.specificity == "EXACT_TYPED"
    assert row.pricing.rates.per_output_token == "0.003"
    assert row.pricing.maximum_credits_per_request == "50"
    assert row.pricing.charge_on_error == "NEVER"
    assert (row.license_id, row.license_slug) == (NEW_ROW["licenseId"], "pro")
    assert row.warnings == ["MODEL_DEPRECATED"]
    assert row.report_seq == 17
    assert row.vendor_cost is not None
    assert (row.vendor_cost.reported, row.vendor_cost.computed) == ("0.0125", "0.0122")
    assert row.credits.refunded == "1.5"
    assert row.refunds[0].created_by.name == "Ada Lovelace"
    assert row.refunds[0].report_seq == 18
    assert row.to_dict() == NEW_ROW, "the wire shape round-trips"


def test_an_inference_row_from_a_later_kaiten_parses() -> None:
    later = copy.deepcopy(NEW_ROW)
    later["warnings"] = ["PRICING_SNAPSHOT_UNREADABLE", "SOMETHING_NEW"]
    later["pricing"]["specificity"] = "A_FUTURE_SPECIFICITY"
    later["somethingNew"] = {"nested": True}
    row = AiInference.model_validate(later)
    assert row.pricing is not None
    assert row.pricing.specificity == "A_FUTURE_SPECIFICITY"
    assert row.model_extra == {"somethingNew": {"nested": True}}


def test_a_conversion_rule_parses_with_and_without_its_authors() -> None:
    old = ConversionRule.model_validate(OLD_RULE)
    assert (old.created_by, old.updated_by, old.granted_by_addons) == (None, None, None)
    new = ConversionRule.model_validate(NEW_RULE)
    assert new.created_by is not None
    assert new.created_by.name == "Ada Lovelace"
    assert new.granted_by_addons is False


def test_an_answer_from_before_the_rule_member_parses() -> None:
    outcome = AiUsageOutcome.model_validate(
        {
            "transactionId": "t1",
            "phase": "commit",
            "status": "COMMITTED",
            "credits": {"charged": "1"},
            "remaining": None,
            "warnings": [],
        }
    )
    assert outcome.rule is None


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("row", [OLD_ROW, NEW_ROW], ids=["old-server", "new-server"])
def test_the_history_reads_both_servers_and_sends_its_filters(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    asynchronous: bool,
    row: dict[str, Any],
) -> None:
    page = {"items": [row], "hasMore": True, "nextCursor": "c2"}
    handler = lambda request: httpx.Response(200, json=page)  # noqa: E731
    filters: dict[str, Any] = {
        "authorized": False,
        "model_slug": "gpt-4o",
        "model": "gpt-4o-2024-11-20",
        "request_type": "COMPLETION",
        "status": "RELEASED",
    }

    async def scenario() -> Any:
        client, recorder = make_async_client(handler)
        async with client:
            return await client.instances.list_ai_inferences(INSTANCE, POOL, **filters), recorder

    if asynchronous:
        result, recorder = asyncio.run(scenario())
    else:
        client, recorder = make_client(handler)
        result = client.instances.list_ai_inferences(INSTANCE, POOL, **filters)
    assert result.items is not None
    assert result.items[0].transaction_id == "req-42"
    assert result.next_cursor == "c2"
    assert dict(recorder.only.url.params) == {
        "authorized": "false",
        "modelSlug": "gpt-4o",
        "model": "gpt-4o-2024-11-20",
        "requestType": "COMPLETION",
        "status": "RELEASED",
    }


@pytest.mark.parametrize("asynchronous", [False, True])
def test_the_organization_listing_walks_every_page_up_to_its_limit(
    make_client: Callable[..., Any], make_async_client: Callable[..., Any], asynchronous: bool
) -> None:
    def row(number: int) -> dict[str, Any]:
        return {
            **NEW_ROW,
            "transactionId": f"req-{number}",
            "instanceSlug": INSTANCE,
            "entitlementSlug": POOL,
        }

    pages = {
        None: {"items": [row(1), row(2)], "hasMore": True, "nextCursor": "c2"},
        "c2": {"items": [row(3), row(4)], "hasMore": True, "nextCursor": "c3"},
        "c3": {"items": [row(5)], "hasMore": False},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/usage/inferences"
        return httpx.Response(200, json=pages[request.url.params.get("cursor")])

    async def scenario() -> Any:
        client, recorder = make_async_client(handler)
        async with client:
            every = await client.instances.list_organization_ai_inferences(instance_slug=INSTANCE)
            capped = await client.instances.list_organization_ai_inferences(limit=3)
            return every, capped, recorder

    if asynchronous:
        every, capped, recorder = asyncio.run(scenario())
    else:
        client, recorder = make_client(handler)
        every = client.instances.list_organization_ai_inferences(instance_slug=INSTANCE)
        capped = client.instances.list_organization_ai_inferences(limit=3)
    assert [item.transaction_id for item in every] == [f"req-{n}" for n in range(1, 6)]
    assert all(isinstance(item, OrganizationAiInference) for item in every)
    assert every[0].instance_slug == INSTANCE
    assert [item.transaction_id for item in capped] == ["req-1", "req-2", "req-3"]
    assert recorder[0].url.params["instanceSlug"] == INSTANCE
    with pytest.raises(ValueError, match="limit"):
        KaitenClient(
            token="ksh_x", base_url="https://kaiten.test"
        ).instances.list_organization_ai_inferences(limit=0)


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.instances.list_ai_inferences(INSTANCE, POOL),
        lambda c: c.instances.list_ai_reservations(INSTANCE, POOL),
        lambda c: c.instances.list_organization_ai_inferences(),
        lambda c: c.instances.refund_ai_inference(INSTANCE, POOL, "t1"),
    ],
    ids=["inferences", "reservations", "organization", "refund"],
)
def test_ai_reads_and_refunds_raise_a_typed_error_while_ai_credits_are_off(
    make_client: Callable[..., Any], call: Callable[[Any], Any]
) -> None:
    client, _ = make_client(lambda request: problem(403, "AIUsage.Disabled"))
    with pytest.raises(AiUsageDisabledError):
        call(client)


def test_a_pool_the_history_cannot_find_is_a_typed_not_found(
    make_client: Callable[..., Any],
) -> None:
    client, _ = make_client(lambda request: problem(404, "ListAiInferences.ContextNotFound"))
    with pytest.raises(AiPoolNotFoundError) as caught:
        client.instances.list_ai_inferences(INSTANCE, POOL)
    assert isinstance(caught.value, NotFoundError)


# -- refunds -----------------------------------------------------------------------------------

REFUND = {
    "id": "8d0e0000-0000-4000-8000-000000000003",
    "credits": "3.5",
    "reason": "duplicate call",
    "reportSeq": 18,
    "createdAt": "2026-11-11T11:00:00Z",
    "createdBy": USER,
}


@pytest.mark.parametrize("asynchronous", [False, True])
def test_a_refund_generates_a_key_and_reuses_it_on_every_retry(
    make_client: Callable[..., Any], make_async_client: Callable[..., Any], asynchronous: bool
) -> None:
    answers = [
        lambda request: httpx.Response(503, json={"title": "Unavailable", "detail": "down"}),
        network_error,
        lambda request: httpx.Response(200, json=REFUND),
    ]
    handler = lambda request: answers.pop(0)(request)  # noqa: E731

    async def scenario() -> Any:
        client, recorder = make_async_client(handler)
        async with client:
            refund = await client.instances.refund_ai_inference(
                INSTANCE, POOL, "req-42", credits=Decimal("3.5"), reason="duplicate call"
            )
            return refund, recorder

    if asynchronous:
        refund, recorder = asyncio.run(scenario())
    else:
        client, recorder = make_client(handler)
        refund = client.instances.refund_ai_inference(
            INSTANCE, POOL, "req-42", credits=Decimal("3.5"), reason="duplicate call"
        )
    assert refund.credits == "3.5"
    assert refund.created_by.name == "Ada Lovelace"
    assert len(recorder) == 3
    keys = {request.headers["idempotency-key"] for request in recorder}
    assert len(keys) == 1, "one refund, one key, however many attempts"
    assert uuid.UUID(keys.pop()).version == 7
    bodies = {request.content for request in recorder}
    assert len(bodies) == 1, "every attempt carries the same bytes"
    assert json.loads(bodies.pop()) == {"credits": "3.5", "reason": "duplicate call"}
    assert recorder[0].url.path == (
        f"/api/instances/{INSTANCE}/entitlements/{POOL}/usage/inferences/req-42/refund"
    )


def test_a_refund_of_everything_left_sends_an_empty_body_under_the_callers_key(
    make_client: Callable[..., Any],
) -> None:
    client, recorder = make_client(lambda request: httpx.Response(200, json=REFUND))
    client.instances.refund_ai_inference(INSTANCE, POOL, "req-42", idempotency_key="refund:1")
    assert json.loads(recorder.only.content) == {}
    assert recorder.only.headers["idempotency-key"] == "refund:1"
    two_keys = {
        client.instances.refund_ai_inference(INSTANCE, POOL, "req-42") and None,
        recorder[-1].headers["idempotency-key"],
    }
    assert len(two_keys) == 2


@pytest.mark.parametrize(
    ("given", "message"),
    [("0.0000001", "6 decimal places"), (0.5, "Decimal"), ("-1", "zero or more")],
)
def test_a_refund_amount_the_api_would_refuse_is_refused_before_sending(
    make_client: Callable[..., Any], given: Any, message: str
) -> None:
    client, recorder = make_client(lambda request: httpx.Response(200, json=REFUND))
    with pytest.raises(ValueError, match=message):
        client.instances.refund_ai_inference(INSTANCE, POOL, "req-42", credits=given)
    with pytest.raises(ValueError, match="transaction id"):
        client.instances.refund_ai_inference(INSTANCE, POOL, "req 42")
    assert list(recorder) == []


@pytest.mark.parametrize(
    ("status_code", "reason", "expected", "family"),
    [
        (404, "ContextNotFound", AiPoolNotFoundError, NotFoundError),
        (404, "InferenceNotFound", AiInferenceNotFoundError, NotFoundError),
        (409, "NotCommitted", AiInferenceNotCommittedError, ConflictError),
        (409, "NothingToRefund", NothingToRefundError, ConflictError),
        (409, "ExceedsRefundable", RefundExceedsRefundableError, ConflictError),
        (409, "IdempotencyKeyReused", IdempotencyKeyReusedError, ConflictError),
        (409, "PoolNotGranted", AiPoolNotGrantedError, ConflictError),
        (422, "IdempotencyKeyRequired", InvalidIdempotencyKeyError, UnprocessableEntityError),
        (422, "InvalidIdempotencyKey", InvalidIdempotencyKeyError, UnprocessableEntityError),
        (422, "InvalidAmount", InvalidRefundError, UnprocessableEntityError),
        (422, "InvalidReason", InvalidRefundError, UnprocessableEntityError),
    ],
)
@pytest.mark.parametrize("asynchronous", [False, True])
def test_each_refund_refusal_raises_its_own_error(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    asynchronous: bool,
    status_code: int,
    reason: str,
    expected: type[Exception],
    family: type[Exception],
) -> None:
    errors = [{"message": "credits left", "location": "body.credits", "value": "5.5"}]
    handler = lambda request: problem(  # noqa: E731
        status_code, f"RefundAiInference.{reason}", errors=errors
    )

    async def scenario() -> Any:
        client, recorder = make_async_client(handler)
        async with client:
            with pytest.raises(expected) as caught:
                await client.instances.refund_ai_inference(INSTANCE, POOL, "req-42")
            return caught, recorder

    if asynchronous:
        caught, recorder = asyncio.run(scenario())
    else:
        client, recorder = make_client(handler)
        with pytest.raises(expected) as caught:
            client.instances.refund_ai_inference(INSTANCE, POOL, "req-42")
    assert isinstance(caught.value, family)
    assert len(recorder) == 1, "a refusal is never retried"
    if expected is RefundExceedsRefundableError:
        assert caught.value.refundable == "5.5"


def test_an_unknown_refund_code_stays_its_status_error(make_client: Callable[..., Any]) -> None:
    client, _ = make_client(lambda request: problem(409, "RefundAiInference.SomethingNew"))
    with pytest.raises(ConflictError) as caught:
        client.instances.refund_ai_inference(INSTANCE, POOL, "req-42")
    assert type(caught.value) is ConflictError


# -- cancellation and interruption -------------------------------------------------------------


def test_a_cancelled_call_is_still_committed_and_the_cancellation_propagates() -> None:
    fake = FakeKaiten()

    async def scenario() -> None:
        transport = httpx.MockTransport(fake)
        async with AsyncKaitenClient(
            token="ksh_test",
            base_url="https://kaiten.test",
            http_client=httpx.AsyncClient(transport=transport),
        ) as client:
            meter = ai.AsyncMeter(client, instance=INSTANCE, entitlement=POOL)
            started = asyncio.Event()

            async def call() -> str:
                started.set()
                await asyncio.sleep(10)
                return "never"

            task = asyncio.create_task(meter.run(call, model="gpt-4o"))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(scenario())
    assert [phase for phase, _ in fake.phases] == ["reserve", "commit"]
    assert fake.commits[0]["requestStatus"] == "CUSTOMER_ERROR"


def test_a_commit_runs_to_its_end_when_its_task_is_cancelled_meanwhile() -> None:
    fake = FakeKaiten()
    committing = asyncio.Event()
    settled: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        value = json.loads(request.content)["value"]
        if value["phase"] == "commit":
            committing.set()
            await asyncio.sleep(0.05)
            settled.append(value["requestStatus"])
        return fake(request)

    async def scenario() -> None:
        async with AsyncKaitenClient(
            token="ksh_test",
            base_url="https://kaiten.test",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ) as client:
            meter = ai.AsyncMeter(client, instance=INSTANCE, entitlement=POOL)

            async def call() -> str:
                return "reply"

            task = asyncio.create_task(meter.run(call, model="gpt-4o"))
            await committing.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert settled == [], "the caller sees the cancellation at once"
            await asyncio.sleep(0.2)

    asyncio.run(scenario())
    assert settled == ["SUCCESS"], "the shielded commit still landed"


def test_an_interrupted_synchronous_call_is_committed_and_re_raised(
    kaiten: tuple[KaitenClient, FakeKaiten],
) -> None:
    client, fake = kaiten

    def call() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        ai.run(client, call, instance=INSTANCE, entitlement=POOL, model="gpt-4o")
    assert [commit["requestStatus"] for commit in fake.commits] == ["CUSTOMER_ERROR"]
    assert ai.request_status_of(asyncio.CancelledError()) == "CUSTOMER_ERROR"


def test_a_meter_releases_settles_without_an_invalid_vendor_cost_and_skips_none(
    kaiten: tuple[KaitenClient, FakeKaiten], caplog: pytest.LogCaptureFixture
) -> None:
    client, fake = kaiten
    meter = ai.Meter(client, instance=INSTANCE, entitlement=POOL)
    assert meter.release(None) is None
    assert fake.reports == []
    meter.release("t1")
    meter.commit("t2", vendor_cost=0.01)  # type: ignore[arg-type]
    meter.commit("t3", request_status="NOT_SENT", vendor_cost="0.01")
    assert [(c["transactionId"], c["requestStatus"]) for c in fake.commits] == [
        ("t1", "NOT_SENT"),
        ("t2", "SUCCESS"),
        ("t3", "NOT_SENT"),
    ]
    assert all("vendorCost" not in commit for commit in fake.commits)
    assert "invalid vendor cost for transaction t2" in caplog.text


def test_a_capabilities_probe_that_fails_leaves_the_original_error(
    make_client: Callable[..., Any],
) -> None:
    fake = FakeKaiten()
    fake.refuse("reserve", lambda request: problem(422, "UNPROCESSABLE"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/ai/capabilities":
            return httpx.Response(401, json={"title": "Unauthorized", "detail": "no"})
        return fake(request)

    client, _ = make_client(handler)
    with pytest.raises(UnprocessableEntityError) as caught:
        client.instances.reserve_ai_usage(INSTANCE, POOL, model="gpt-4o")
    assert type(caught.value) is UnprocessableEntityError
