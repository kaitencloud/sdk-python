# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""AI credits: the two phases on the wire, their errors, their retries, and ``ai.run``."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from ai_fakes import FakeKaiten, network_error, problem, status

from kaitencloud import (
    AiUsageUnsupportedError,
    APIStatusError,
    AsyncKaitenClient,
    ConflictError,
    InsufficientCreditsError,
    KaitenClient,
    ModelNotAuthorizedError,
    ServiceUnavailableError,
    ThresholdExceededError,
    TransactionIdReusedError,
    UnknownModelError,
    UnprocessableEntityError,
    ai,
)

INSTANCE, POOL = "acme-prod", "chat-credits"


@pytest.fixture
def kaiten(make_client: Callable[..., Any]) -> tuple[KaitenClient, FakeKaiten]:
    fake = FakeKaiten()
    client, _ = make_client(fake)
    return client, fake


# -- the phases on the wire ---------------------------------------------------------------


def test_a_reservation_sends_the_ai_variant_and_a_fresh_uuid7(
    kaiten: tuple[KaitenClient, FakeKaiten],
) -> None:
    client, fake = kaiten
    answer = client.instances.reserve_ai_usage(
        INSTANCE,
        POOL,
        model="gpt-4o",
        usage={"input_tokens": 1000, "output_tokens": 4000},
        ttl_seconds=600,
    )

    report = fake.reports[0]
    assert report.request.url.path == f"/api/instances/{INSTANCE}/entitlements/{POOL}/usage"
    assert report.body == {
        "value": {
            "type": "ai_usage",
            "phase": "reserve",
            "transactionId": report.transaction_id,
            "model": "gpt-4o",
            "requestType": "COMPLETION",
            "usage": {"inputTokens": 1000, "outputTokens": 4000},
            "ttlSeconds": 600,
        }
    }
    assert uuid.UUID(report.transaction_id).version == 7
    assert report.key is not None
    assert uuid.UUID(report.key).version == 4
    assert answer.ai is not None
    assert answer.ai.transaction_id == report.transaction_id
    assert answer.ai.status == "RESERVED"
    assert answer.ai.credits.reserved == "6.6"
    assert answer.reserved == "6.6"
    assert answer.value.type == "number"


def test_a_commit_sends_only_what_the_reservation_does_not_know(
    kaiten: tuple[KaitenClient, FakeKaiten],
) -> None:
    client, fake = kaiten
    answer = client.instances.commit_ai_usage(
        INSTANCE,
        POOL,
        transaction_id="01JB2K7Z9Q",
        usage={"input_tokens": 1000, "cache_read_input_tokens": 200, "output_tokens": 400},
    )

    assert fake.reports[0].body == {
        "value": {
            "type": "ai_usage",
            "phase": "commit",
            "transactionId": "01JB2K7Z9Q",
            "requestStatus": "SUCCESS",
            "usage": {"inputTokens": 1000, "cacheReadInputTokens": 200, "outputTokens": 400},
        }
    }
    assert answer.ai is not None
    assert answer.ai.credits.charged == "1.2"


def test_a_commit_without_a_reservation_names_what_ran(
    kaiten: tuple[KaitenClient, FakeKaiten],
) -> None:
    client, fake = kaiten
    client.instances.commit_ai_usage(
        INSTANCE,
        POOL,
        transaction_id="run-1:0",
        model="claude-sonnet-4-5",
        request_type="COMPLETION",
        usage={"units": "2.5", "unit_type": "second", "duration_ms": 2500},
        metadata={"feature": "summaries"},
    )
    assert fake.reports[0].body == {
        "value": {
            "type": "ai_usage",
            "phase": "commit",
            "transactionId": "run-1:0",
            "requestStatus": "SUCCESS",
            "model": "claude-sonnet-4-5",
            "requestType": "COMPLETION",
            "usage": {"durationMs": 2500, "units": "2.5", "unitType": "second"},
        },
        "metadata": {"feature": "summaries"},
    }


@pytest.mark.parametrize("transaction_id", ["", "has space", "a" * 129, "slash/no"])
def test_a_transaction_id_the_api_would_refuse_is_refused_before_sending(
    kaiten: tuple[KaitenClient, FakeKaiten], transaction_id: str
) -> None:
    client, fake = kaiten
    with pytest.raises(ValueError, match="transaction id"):
        client.instances.commit_ai_usage(INSTANCE, POOL, transaction_id=transaction_id)
    assert fake.reports == []


@pytest.mark.parametrize(
    "usage",
    [{"input_tokens": -1}, {"output_tokens": 1.5}, {"units": "-2"}, {"tokens": 3}],
)
def test_a_malformed_usage_is_refused_before_sending(
    kaiten: tuple[KaitenClient, FakeKaiten], usage: Any
) -> None:
    client, fake = kaiten
    with pytest.raises(ValueError, match="usage"):
        client.instances.reserve_ai_usage(INSTANCE, POOL, model="gpt-4o", usage=usage)
    assert fake.reports == []


# -- errors ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status_code", "code", "expected"),
    [
        (409, "ThresholdExceeded", InsufficientCreditsError),
        (409, "TransactionIdReused", TransactionIdReusedError),
        (422, "UnknownModel", UnknownModelError),
        (422, "ModelNotAuthorized", ModelNotAuthorizedError),
        (422, "AiUsageUnsupportedEntitlement", AiUsageUnsupportedError),
        (422, "InvalidValueType", AiUsageUnsupportedError),
        (422, None, AiUsageUnsupportedError),
    ],
)
def test_each_refusal_raises_its_own_error(
    kaiten: tuple[KaitenClient, FakeKaiten],
    status_code: int,
    code: str | None,
    expected: type[Exception],
) -> None:
    client, fake = kaiten
    fake.refuse("reserve", problem(status_code, code))
    with pytest.raises(expected) as caught:
        client.instances.reserve_ai_usage(INSTANCE, POOL, model="gpt-4o")
    assert len(fake.reports) == 1, "a 4xx is never retried"
    assert caught.value.__cause__ is not None


def test_running_out_of_credits_is_also_a_reached_threshold(
    kaiten: tuple[KaitenClient, FakeKaiten],
) -> None:
    client, fake = kaiten
    fake.refuse("reserve", problem(409, "ThresholdExceeded"))
    with pytest.raises(ThresholdExceededError) as caught:
        client.instances.reserve_ai_usage(INSTANCE, POOL, model="gpt-4o")
    assert isinstance(caught.value, ConflictError)
    assert caught.value.code == "ReportEntitlementUsageMetric.ThresholdExceeded"


@pytest.mark.parametrize(
    "code", ["InvalidAiUsage", "TransactionIdRequired", "AiUsageRequiresAppend"]
)
def test_a_malformed_ai_body_is_not_mistaken_for_an_old_server(
    kaiten: tuple[KaitenClient, FakeKaiten], code: str
) -> None:
    client, fake = kaiten
    fake.refuse("commit", problem(422, code))
    with pytest.raises(UnprocessableEntityError) as caught:
        client.instances.commit_ai_usage(INSTANCE, POOL, transaction_id="t1")
    assert not isinstance(caught.value, AiUsageUnsupportedError)


# -- retries --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure", [status(500), status(502), status(503), status(504), network_error]
)
def test_a_commit_is_retried_under_one_key_and_one_transaction_id(
    kaiten: tuple[KaitenClient, FakeKaiten], failure: Any
) -> None:
    client, fake = kaiten
    fake.refuse("commit", failure, failure)
    client.instances.commit_ai_usage(INSTANCE, POOL, transaction_id="t1")

    assert len(fake.reports) == 3
    assert {report.key for report in fake.reports} == {fake.reports[0].key}
    assert {report.transaction_id for report in fake.reports} == {"t1"}


def test_a_commit_gives_up_after_three_retries(kaiten: tuple[KaitenClient, FakeKaiten]) -> None:
    client, fake = kaiten
    fake.refuse("commit", *[status(503)] * 5)
    with pytest.raises(ServiceUnavailableError):
        client.instances.commit_ai_usage(INSTANCE, POOL, transaction_id="t1")
    assert len(fake.reports) == 4


@pytest.mark.parametrize("code", [408, 429, 501])
def test_a_commit_is_not_retried_outside_its_statuses(
    kaiten: tuple[KaitenClient, FakeKaiten], code: int
) -> None:
    client, fake = kaiten
    fake.refuse("commit", status(code))
    with pytest.raises(APIStatusError):
        client.instances.commit_ai_usage(INSTANCE, POOL, transaction_id="t1")
    assert len(fake.reports) == 1


def test_each_logical_call_has_its_own_key(kaiten: tuple[KaitenClient, FakeKaiten]) -> None:
    client, fake = kaiten
    client.instances.commit_ai_usage(INSTANCE, POOL, transaction_id="t1")
    client.instances.commit_ai_usage(INSTANCE, POOL, transaction_id="t1")
    assert fake.reports[0].key != fake.reports[1].key


def test_the_client_retry_setting_does_not_change_the_ai_policy(
    make_client: Callable[..., Any],
) -> None:
    fake = FakeKaiten()
    client, _ = make_client(fake, max_retries=0)
    fake.refuse("reserve", status(503))
    client.instances.reserve_ai_usage(INSTANCE, POOL, model="gpt-4o")
    assert len(fake.reports) == 2


# -- the module functions --------------------------------------------------------------------


def test_the_module_phases_go_through_the_client(kaiten: tuple[KaitenClient, FakeKaiten]) -> None:
    client, fake = kaiten
    reserved = ai.reserve(client, instance=INSTANCE, entitlement=POOL, model="gpt-4o")
    assert reserved.ai is not None
    ai.commit(
        client,
        instance=INSTANCE,
        entitlement=POOL,
        transaction_id=reserved.ai.transaction_id,
        request_status="NOT_SENT",
    )
    assert fake.phases == [
        ("reserve", reserved.ai.transaction_id),
        ("commit", reserved.ai.transaction_id),
    ]
    assert fake.commits[0]["requestStatus"] == "NOT_SENT"
    assert all(
        report.request.url.path == f"/api/instances/{INSTANCE}/entitlements/{POOL}/usage"
        for report in fake.reports
    )


def test_run_reserves_calls_and_commits_the_usage(kaiten: tuple[KaitenClient, FakeKaiten]) -> None:
    client, fake = kaiten
    calls: list[str] = []

    def call() -> dict[str, Any]:
        calls.append("provider")
        return {"usage": {"prompt_tokens": 120, "completion_tokens": 30}}

    result = ai.run(
        client,
        call,
        instance=INSTANCE,
        entitlement=POOL,
        model="gpt-4o",
        estimate={"input_tokens": 100, "output_tokens": 1024},
        usage=lambda reply: ai.from_openai(reply["usage"]),
        transaction_id="op-1",
    )

    assert calls == ["provider"]
    assert result["usage"]["prompt_tokens"] == 120
    assert fake.phases == [("reserve", "op-1"), ("commit", "op-1")]
    assert fake.reserves[0]["usage"] == {"inputTokens": 100, "outputTokens": 1024}
    assert fake.commits[0] == {
        "type": "ai_usage",
        "phase": "commit",
        "transactionId": "op-1",
        "requestStatus": "SUCCESS",
        "usage": {"inputTokens": 120, "outputTokens": 30},
    }


def test_run_does_not_call_the_provider_when_the_pool_is_empty(
    kaiten: tuple[KaitenClient, FakeKaiten],
) -> None:
    client, fake = kaiten
    fake.refuse("reserve", problem(409, "ThresholdExceeded"))
    called: list[bool] = []
    with pytest.raises(InsufficientCreditsError):
        ai.run(
            client, lambda: called.append(True), instance=INSTANCE, entitlement=POOL, model="gpt-4o"
        )
    assert called == []
    assert fake.commits == []


class ProviderError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ConnectionRefusedError("refused"), "NOT_SENT"),
        (TypeError("possibly raised after sending"), "PROVIDER_ERROR"),
        (httpx.ConnectError("connect"), "NOT_SENT"),
        (httpx.ConnectTimeout("connect"), "NOT_SENT"),
        (httpx.PoolTimeout("pool"), "NOT_SENT"),
        (httpx.ReadTimeout("read"), "PROVIDER_ERROR"),
        (httpx.ReadError("reset after send"), "PROVIDER_ERROR"),
        (httpx.WriteError("partial write"), "PROVIDER_ERROR"),
        (httpx.RemoteProtocolError("invalid response"), "PROVIDER_ERROR"),
        (RuntimeError("unknown failure"), "PROVIDER_ERROR"),
        (ProviderError(500), "PROVIDER_ERROR"),
        (ProviderError(429), "PROVIDER_ERROR"),
        (ProviderError(400), "CUSTOMER_ERROR"),
    ],
)
def test_run_commits_how_a_failed_call_ended_and_reraises(
    kaiten: tuple[KaitenClient, FakeKaiten], error: Exception, expected: str
) -> None:
    client, fake = kaiten

    def call() -> None:
        raise error

    with pytest.raises(type(error)):
        ai.run(client, call, instance=INSTANCE, entitlement=POOL, model="gpt-4o")
    assert [commit["requestStatus"] for commit in fake.commits] == [expected]


def test_run_survives_a_commit_that_keeps_failing(
    kaiten: tuple[KaitenClient, FakeKaiten], caplog: pytest.LogCaptureFixture
) -> None:
    client, fake = kaiten
    fake.refuse("commit", *[status(503)] * 4)
    with caplog.at_level(logging.ERROR, logger="kaitencloud.ai"):
        result = ai.run(
            client, lambda: "reply", instance=INSTANCE, entitlement=POOL, model="gpt-4o"
        )
    assert result == "reply"
    assert len(fake.commits) == 4
    assert "reservation will expire" in caplog.text


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("invalid_usage", [False, True])
@pytest.mark.parametrize("settlement_fails", [False, True])
def test_run_preserves_success_when_usage_extraction_or_validation_fails(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    caplog: pytest.LogCaptureFixture,
    asynchronous: bool,
    invalid_usage: bool,
    settlement_fails: bool,
) -> None:
    fake = FakeKaiten()
    if settlement_fails:
        fake.refuse("commit", *[status(503)] * 4)
    reply = object()

    def usage(result: Any) -> Any:
        assert result is reply
        if invalid_usage:
            return {"input_tokens": -1}
        raise ValueError("normalizer failed")

    async def scenario() -> Any:
        client, _ = make_async_client(fake)
        async with client:

            async def call() -> Any:
                return reply

            return await ai.run(
                client, call, instance=INSTANCE, entitlement=POOL, model="gpt-4o", usage=usage
            )

    with caplog.at_level(logging.ERROR, logger="kaitencloud.ai"):
        if asynchronous:
            result = asyncio.run(scenario())
        else:
            client, _ = make_client(fake)
            with client:
                result = ai.run(
                    client,
                    lambda: reply,
                    instance=INSTANCE,
                    entitlement=POOL,
                    model="gpt-4o",
                    usage=usage,
                )

    assert result is reply
    assert len(fake.reserves) == 1
    assert len(fake.commits) == (4 if settlement_fails else 1)
    assert all(commit["requestStatus"] == "SUCCESS" for commit in fake.commits)
    assert all("usage" not in commit for commit in fake.commits)
    assert {commit["transactionId"] for commit in fake.commits} == {
        fake.reserves[0]["transactionId"]
    }
    assert "attempting settlement without usage" in caplog.text
    if settlement_fails:
        assert "reservation will expire" in caplog.text


def test_a_timeout_class_name_does_not_prove_the_call_was_not_sent() -> None:
    class ConnectTimeoutError(Exception):
        pass

    assert ai.request_status_of(ConnectTimeoutError()) == "PROVIDER_ERROR"


def test_run_lets_the_call_through_a_server_without_ai_credits(
    kaiten: tuple[KaitenClient, FakeKaiten], caplog: pytest.LogCaptureFixture
) -> None:
    client, fake = kaiten
    fake.refuse("reserve", problem(422, None))
    with caplog.at_level(logging.ERROR, logger="kaitencloud.ai"):
        result = ai.run(
            client, lambda: "reply", instance=INSTANCE, entitlement=POOL, model="gpt-4o"
        )
    assert result == "reply"
    assert fake.phases == [("reserve", fake.reports[0].transaction_id)]
    assert "NOT being reported" in caplog.text


def test_a_meter_logs_an_unsupported_server_once_and_stops_reporting(
    kaiten: tuple[KaitenClient, FakeKaiten], caplog: pytest.LogCaptureFixture
) -> None:
    client, fake = kaiten
    fake.refuse("reserve", problem(422, "AiUsageUnsupportedEntitlement"))
    meter = ai.Meter(client, instance=INSTANCE, entitlement=POOL)
    with caplog.at_level(logging.ERROR, logger="kaitencloud.ai"):
        for _ in range(3):
            assert meter.run(lambda: "reply", model="gpt-4o") == "reply"
    assert len(fake.reports) == 1
    assert caplog.text.count("NOT being reported") == 1


def test_the_async_client_runs_the_same_way(make_async_client: Callable[..., Any]) -> None:
    fake = FakeKaiten()

    async def scenario() -> str:
        client, _ = make_async_client(fake)
        async with client:

            async def call() -> str:
                return "reply"

            reserved = await ai.reserve(client, instance=INSTANCE, entitlement=POOL, model="gpt-4o")
            assert reserved.ai is not None
            await ai.commit(
                client,
                instance=INSTANCE,
                entitlement=POOL,
                transaction_id=reserved.ai.transaction_id,
            )
            return await ai.run(
                client,
                call,
                instance=INSTANCE,
                entitlement=POOL,
                model="gpt-4o",
                usage=lambda _: {"output_tokens": 3},
            )

    assert asyncio.run(scenario()) == "reply"
    assert [phase for phase, _ in fake.phases] == ["reserve", "commit", "reserve", "commit"]
    assert fake.commits[-1]["usage"] == {"outputTokens": 3}


def test_an_async_client_is_metered_by_an_async_meter() -> None:
    client = AsyncKaitenClient(token="ksh_x", base_url="https://kaiten.test")
    meter = ai.AsyncMeter(client, instance=INSTANCE, entitlement=POOL)
    assert repr(meter) == "<AsyncMeter instance='acme-prod' entitlement='chat-credits'>"
    assert meter.entitlement == POOL
    assert not hasattr(meter, "pool")


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("entry_point", ["reserve", "commit", "run", "meter", "runner"])
@pytest.mark.parametrize("include_entitlement", [False, True])
def test_high_level_ai_rejects_the_old_pool_keyword_before_reporting(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    asynchronous: bool,
    entry_point: str,
    include_entitlement: bool,
) -> None:
    from kaitencloud._async.ai import async_run
    from kaitencloud._sync.ai import run

    fake = FakeKaiten()
    factory = make_async_client if asynchronous else make_client
    client, _ = factory(fake)
    options: dict[str, Any] = {"instance": INSTANCE, "pool": POOL}
    if include_entitlement:
        options["entitlement"] = POOL
    args: tuple[Any, ...] = (client,)
    if entry_point == "meter":
        target = ai.AsyncMeter if asynchronous else ai.Meter
    elif entry_point == "runner":
        target = async_run if asynchronous else run
    else:
        target = getattr(ai, entry_point)
    if entry_point in ("run", "runner"):
        args += (lambda: pytest.fail("provider must not be called"),)
    if entry_point == "commit":
        options["transaction_id"] = "t1"
    elif entry_point != "meter":
        options["model"] = "gpt-4o"

    with pytest.raises(TypeError, match="pool"):
        target(*args, **options)
    assert fake.reports == []
    if asynchronous:
        asyncio.run(client.close())
    else:
        client.close()


# -- transaction ids, normalisers, estimation ----------------------------------------------


def test_transaction_ids_are_uuid7_and_sort_by_time() -> None:
    ids = [ai.new_transaction_id() for _ in range(50)]
    assert all(uuid.UUID(value).version == 7 for value in ids)
    assert all(uuid.UUID(value).variant == uuid.RFC_4122 for value in ids)
    assert len(set(ids)) == 50
    assert [value[:8] for value in ids] == sorted(value[:8] for value in ids)


class Usage:
    """A provider usage object: attributes, not keys."""

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        # Chat Completions: prompt_tokens includes the cached and the cache-written tokens.
        (
            Usage(
                prompt_tokens=1000,
                completion_tokens=500,
                prompt_tokens_details=Usage(cached_tokens=300, cache_write_tokens=100),
                completion_tokens_details=Usage(reasoning_tokens=200),
            ),
            {
                "input_tokens": 600,
                "cache_read_input_tokens": 300,
                "cache_write_input_tokens": 100,
                "output_tokens": 500,
            },
        ),
        # Responses API, as a dictionary.
        (
            {
                "input_tokens": 80,
                "input_tokens_details": {"cached_tokens": 50, "cache_write_tokens": 0},
                "output_tokens": 20,
                "output_tokens_details": {"reasoning_tokens": 5},
            },
            {"input_tokens": 30, "cache_read_input_tokens": 50, "output_tokens": 20},
        ),
        # Embeddings: no output.
        (Usage(prompt_tokens=12, total_tokens=12), {"input_tokens": 12, "output_tokens": 0}),
        # Images.
        (
            Usage(input_tokens=50, output_tokens=4160, input_tokens_details=Usage(image_tokens=0)),
            {"input_tokens": 50, "output_tokens": 4160},
        ),
        # A transcription billed by duration.
        ({"type": "duration", "seconds": 12.5}, {"duration_ms": 12500}),
        # Inconsistent counts clamp at zero.
        (
            {"prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": 40}},
            {"input_tokens": 0, "cache_read_input_tokens": 40, "output_tokens": 0},
        ),
        (None, {}),
    ],
)
def test_from_openai_makes_the_token_counts_disjoint(usage: Any, expected: Any) -> None:
    assert ai.from_openai(usage) == expected


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        (
            Usage(
                input_tokens=40,
                cache_read_input_tokens=1000,
                cache_creation_input_tokens=200,
                output_tokens=300,
            ),
            {
                "input_tokens": 40,
                "cache_read_input_tokens": 1000,
                "cache_write_input_tokens": 200,
                "output_tokens": 300,
            },
        ),
        (
            {"input_tokens": 5, "output_tokens": 1, "cache_read_input_tokens": None},
            {"input_tokens": 5, "output_tokens": 1},
        ),
        (None, {}),
    ],
)
def test_from_anthropic_maps_one_to_one(usage: Any, expected: Any) -> None:
    assert ai.from_anthropic(usage) == expected


def test_usages_add_up_field_by_field() -> None:
    assert ai.add_usage(
        {"input_tokens": 3, "output_tokens": 1},
        None,
        {"output_tokens": 4, "units": "1.5", "unit_type": "second"},
        {"units": 2},
    ) == {"input_tokens": 3, "output_tokens": 5, "units": "3.5", "unit_type": "second"}


def request(operation: str, request_type: Any = "COMPLETION", **params: Any) -> ai.AiRequest:
    return ai.AiRequest("openai", operation, "gpt-4o", request_type, params)


def test_the_default_estimate_is_prompt_bytes_over_four_and_the_output_ceiling() -> None:
    messages = [{"role": "user", "content": "x" * 397}]  # 432 bytes, serialized
    estimate = ai.default_estimator(
        request("chat.completions.create", messages=messages, max_completion_tokens=800)
    )
    assert estimate == {"input_tokens": 108, "output_tokens": 800}


def test_without_a_ceiling_the_output_defaults_per_request_type() -> None:
    assert ai.default_estimator(request("responses.create", input="hello")) == {
        "input_tokens": 3,
        "output_tokens": 1024,
    }
    assert ai.default_estimator(request("embeddings.create", "EMBEDDING", input=["a", "b"])) == {
        "input_tokens": 3,
        "output_tokens": 0,
    }
    assert ai.default_estimator(request("audio.transcriptions.create", "AUDIO")) == {}


def test_an_image_generation_reserves_its_images() -> None:
    assert ai.default_estimator(request("images.generate", "IMAGE_GENERATION", n=3)) == {
        "units": 3,
        "unit_type": "image",
    }
    assert ai.default_estimator(request("images.generate", "IMAGE_GENERATION")) == {
        "units": 1,
        "unit_type": "image",
    }


@pytest.mark.parametrize(
    ("timeout", "expected"),
    [
        (600.0, 600),
        (12.2, 13),
        (httpx.Timeout(30.0, connect=10.0), 30),
        (httpx.Timeout(1.0, pool=90.0), 90),
        (httpx.Timeout(None), None),
        (7200, 3600),
        (None, None),
        (0, None),
        (True, None),
    ],
)
def test_a_reservation_lasts_as_long_as_the_provider_timeout(timeout: Any, expected: Any) -> None:
    from kaitencloud._ai import ttl_from_timeout

    assert ttl_from_timeout(timeout) == expected
