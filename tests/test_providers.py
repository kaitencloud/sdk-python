# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Synthetic provider clients and streams: no optional SDK or network required."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from ai_fakes import FakeKaiten, problem, status

from kaitencloud import InsufficientCreditsError
from kaitencloud.anthropic import wrap_anthropic
from kaitencloud.openai import wrap_openai


class Stream:
    def __init__(self, events: list[Any]) -> None:
        self.events = iter(events)
        self.closed = False

    def __iter__(self) -> Stream:
        return self

    def __next__(self) -> Any:
        return next(self.events)

    def __aiter__(self) -> Stream:
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self.events)
        except StopIteration:
            raise StopAsyncIteration from None

    def close(self) -> None:
        self.closed = True


class AsyncStream(Stream):
    async def close(self) -> None:  # type: ignore[override]
        self.closed = True


class Manager:
    def __init__(self, stream: Stream) -> None:
        self.stream = stream

    def __enter__(self) -> Stream:
        return self.stream

    def __exit__(self, *args: Any) -> None:
        self.stream.close()

    async def __aenter__(self) -> Stream:
        return self.stream

    async def __aexit__(self, *args: Any) -> None:
        await self.stream.close()  # type: ignore[func-returns-value]


class Provider:
    def __init__(self, result: Any, asynchronous: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.result = result
        self.timeout = 30
        self.unlisted = object()

        def call(**kwargs: Any) -> Any:
            self.calls.append(kwargs)
            if isinstance(self.result, BaseException):
                raise self.result
            return self.result

        async def async_call(**kwargs: Any) -> Any:
            return call(**kwargs)

        method = async_call if asynchronous else call
        resource = SimpleNamespace(create=method, unlisted=self.unlisted)
        self.chat = SimpleNamespace(completions=resource)
        self.responses = resource
        self.embeddings = resource
        self.images = SimpleNamespace(generate=method)
        self.audio = SimpleNamespace(transcriptions=resource, speech=resource)
        self.messages = SimpleNamespace(
            create=method, stream=lambda **kwargs: Manager(call(**kwargs))
        )

    def copy(self, **kwargs: Any) -> Provider:
        return self

    with_options = copy


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
def test_provider_reserves_calls_and_commits_without_changing_the_result(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    asynchronous: bool,
    provider_name: str,
) -> None:
    fake = FakeKaiten()
    usage = (
        {"prompt_tokens": 12, "completion_tokens": 3}
        if provider_name == "openai"
        else {"input_tokens": 12, "output_tokens": 3}
    )
    result = SimpleNamespace(usage=usage)
    provider = Provider(result, asynchronous)
    wrap = wrap_openai if provider_name == "openai" else wrap_anthropic

    async def scenario() -> Any:
        client, _ = make_async_client(fake)
        async with client:
            wrapped = wrap(provider, kaiten=client, instance="i", entitlement="p")
            assert wrapped.unlisted is provider.unlisted
            method = (
                wrapped.chat.completions.create
                if provider_name == "openai"
                else wrapped.messages.create
            )
            return await method(model="m", messages=[], max_tokens=5)

    if asynchronous:
        answer = asyncio.run(scenario())
    else:
        client, _ = make_client(fake)
        with client:
            wrapped = wrap(provider, kaiten=client, instance="i", entitlement="p")
            assert wrapped.unlisted is provider.unlisted
            method = (
                wrapped.chat.completions.create
                if provider_name == "openai"
                else wrapped.messages.create
            )
            answer = method(model="m", messages=[], max_tokens=5)
    assert answer is result
    assert [phase for phase, _ in fake.phases] == ["reserve", "commit"]
    assert fake.reserves[0]["ttlSeconds"] == 30
    assert fake.commits[0]["usage"] == {"inputTokens": 12, "outputTokens": 3}


def test_refusal_prevents_the_provider_and_unsupported_degrades_once(
    make_client: Callable[..., Any],
) -> None:
    for code, status_code in [("ThresholdExceeded", 409), ("InvalidValueType", 422)]:
        fake = FakeKaiten()
        fake.refuse("reserve", problem(status_code, code))
        client, _ = make_client(fake)
        provider = Provider("reply")
        with client:
            wrapped = wrap_openai(provider, kaiten=client, instance="i", entitlement="p")
            if status_code == 409:
                with pytest.raises(InsufficientCreditsError):
                    wrapped.responses.create(model="m", input="x")
                assert provider.calls == []
            else:
                for _ in range(2):
                    assert wrapped.responses.create(model="m", input="x") == "reply"
                assert len(fake.reports) == 1


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("abandoned", [False, True])
@pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
def test_stream_completion_and_partial_close(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    asynchronous: bool,
    abandoned: bool,
    provider_name: str,
) -> None:
    fake = FakeKaiten()
    if provider_name == "openai":
        events = [
            {"choices": [{"delta": {"content": "x"}}]},
            {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 4}},
        ]
    else:
        events = [
            {
                "type": "message_start",
                "message": {
                    "usage": {"input_tokens": 20, "output_tokens": 1, "cache_read_input_tokens": 6}
                },
            },
            {"type": "message_delta", "usage": {"output_tokens": 2}},
            {"type": "message_delta", "usage": {"output_tokens": 4}},
            {"type": "message_stop"},
        ]
    raw = AsyncStream(events) if asynchronous else Stream(events)
    provider = Provider(raw, asynchronous)
    wrap = wrap_openai if provider_name == "openai" else wrap_anthropic

    async def scenario() -> None:
        client, _ = make_async_client(fake)
        async with client:
            wrapped = wrap(provider, kaiten=client, instance="i", entitlement="p")
            if provider_name == "anthropic":
                async with wrapped.messages.stream(model="m", messages=[], max_tokens=5) as stream:
                    if abandoned:
                        await stream.__anext__()
                    else:
                        async for _ in stream:
                            pass
            else:
                stream = await wrapped.chat.completions.create(
                    model="m", messages=[], stream=True, stream_options={"other": True}
                )
                if abandoned:
                    await stream.__anext__()
                else:
                    async for _ in stream:
                        pass
                await stream.close()
                await stream.close()

    if asynchronous:
        asyncio.run(scenario())
    else:
        client, _ = make_client(fake)
        with client:
            wrapped = wrap(provider, kaiten=client, instance="i", entitlement="p")
            if provider_name == "anthropic":
                with wrapped.messages.stream(model="m", messages=[], max_tokens=5) as stream:
                    next(stream) if abandoned else list(stream)
            else:
                stream = wrapped.chat.completions.create(
                    model="m", messages=[], stream=True, stream_options={"other": True}
                )
                next(stream) if abandoned else list(stream)
                stream.close()
                stream.close()
    assert raw.closed
    assert len(fake.commits) == 1
    assert fake.commits[0]["requestStatus"] == ("CUSTOMER_ERROR" if abandoned else "SUCCESS")
    if not abandoned:
        assert fake.commits[0]["usage"]["outputTokens"] == 4
    if provider_name == "anthropic":
        assert fake.commits[0]["usage"]["cacheReadInputTokens"] == 6
    else:
        assert provider.calls[0]["stream_options"] == {"other": True, "include_usage": True}


def test_commit_failure_does_not_replace_success_and_copy_stays_wrapped(
    make_client: Callable[..., Any],
) -> None:
    fake = FakeKaiten()
    fake.refuse("commit", *[status(503)] * 4)
    client, _ = make_client(fake)
    provider = Provider("reply")
    with client:
        wrapped = wrap_openai(provider, kaiten=client, instance="i", entitlement="p")
        assert wrapped.with_options(timeout=1).responses.create(model="m") == "reply"
    assert len(fake.commits) == 4


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
def test_drop_in_is_a_provider_subclass_and_uses_the_same_loop(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
    asynchronous: bool,
    provider_name: str,
) -> None:
    from kaitencloud._provider_clients import drop_in

    class Base(Provider):
        def __init__(self, **kwargs: Any) -> None:
            assert "entitlement" not in kwargs
            super().__init__(SimpleNamespace(usage={"output_tokens": 2}), asynchronous)

    name = ("Async" if asynchronous else "") + (
        "OpenAI" if provider_name == "openai" else "Anthropic"
    )
    monkeypatch.setitem(sys.modules, provider_name, SimpleNamespace(**{name: Base}))
    client_type = drop_in(provider_name, name, f"kaitencloud.{provider_name}")
    fake = FakeKaiten()

    def call(client: Any) -> Any:
        provider = client_type(kaiten=client, instance="i", entitlement="p")
        assert isinstance(provider, Base)
        method = (
            provider.responses.create if provider_name == "openai" else provider.messages.create
        )
        return method(model="m")

    async def scenario() -> None:
        client, _ = make_async_client(fake)
        async with client:
            await call(client)

    if asynchronous:
        asyncio.run(scenario())
    else:
        client, _ = make_client(fake)
        with client:
            call(client)
    assert len(fake.commits) == 1
    assert all(
        report.request.url.path == "/api/instances/i/entitlements/p/usage"
        for report in fake.reports
    )


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("failed", [False, True])
def test_responses_terminal_event_settles_once(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    asynchronous: bool,
    failed: bool,
) -> None:
    fake = FakeKaiten()
    events = [
        {"type": "response.output_text.delta", "delta": "x"},
        {
            "type": "response.failed" if failed else "response.completed",
            "response": {
                "usage": {
                    "input_tokens": 10,
                    "input_tokens_details": {"cached_tokens": 3},
                    "output_tokens": 2,
                }
            },
        },
    ]
    raw = AsyncStream(events) if asynchronous else Stream(events)
    provider = Provider(raw, asynchronous)

    async def scenario() -> None:
        client, _ = make_async_client(fake)
        async with client:
            wrapped = wrap_openai(provider, kaiten=client, instance="i", entitlement="p")
            stream = await wrapped.responses.create(model="m", stream=True)
            async with stream:
                async for _ in stream:
                    pass

    if asynchronous:
        asyncio.run(scenario())
    else:
        client, _ = make_client(fake)
        with client:
            wrapped = wrap_openai(provider, kaiten=client, instance="i", entitlement="p")
            with wrapped.responses.create(model="m", stream=True) as stream:
                list(stream)
    assert "stream_options" not in provider.calls[0]
    assert len(fake.commits) == 1
    assert fake.commits[0]["requestStatus"] == ("PROVIDER_ERROR" if failed else "SUCCESS")
    assert fake.commits[0]["usage"] == {
        "inputTokens": 7,
        "cacheReadInputTokens": 3,
        "outputTokens": 2,
    }


@pytest.mark.parametrize(
    "operation",
    ["embeddings.create", "images.generate", "audio.transcriptions.create", "audio.speech.create"],
)
def test_remaining_openai_allow_list(make_client: Callable[..., Any], operation: str) -> None:
    fake = FakeKaiten()
    if operation == "images.generate":
        result = SimpleNamespace(data=[object(), object()], usage=None)
    elif operation == "audio.speech.create":
        result = b"synthetic audio"
    elif operation == "audio.transcriptions.create":
        result = SimpleNamespace(usage={"type": "duration", "seconds": 2.5})
    else:
        result = SimpleNamespace(usage={"prompt_tokens": 3})
    client, _ = make_client(fake)
    with client:
        target = wrap_openai(Provider(result), kaiten=client, instance="i", entitlement="p")
        for part in operation.split("."):
            target = getattr(target, part)
        assert target(model="m") is result
    assert len(fake.commits) == 1
    if operation == "images.generate":
        assert fake.commits[0]["usage"] == {"units": "2", "unitType": "image"}
    elif operation == "audio.speech.create":
        assert "usage" not in fake.commits[0]
    elif operation == "audio.transcriptions.create":
        assert fake.commits[0]["usage"] == {"durationMs": 2500}


@pytest.mark.parametrize("asynchronous", [False, True])
def test_unread_stream_releases_on_close(
    make_client: Callable[..., Any], make_async_client: Callable[..., Any], asynchronous: bool
) -> None:
    fake = FakeKaiten()
    provider = Provider(AsyncStream([]) if asynchronous else Stream([]), asynchronous)

    async def scenario() -> None:
        client, _ = make_async_client(fake)
        async with client:
            stream = await wrap_openai(
                provider, kaiten=client, instance="i", entitlement="p"
            ).responses.create(model="m", stream=True)
            await stream.close()

    if asynchronous:
        asyncio.run(scenario())
    else:
        client, _ = make_client(fake)
        with client:
            stream = wrap_openai(
                provider, kaiten=client, instance="i", entitlement="p"
            ).responses.create(model="m", stream=True)
            stream.close()
    assert fake.commits[0]["requestStatus"] == "NOT_SENT"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_stream_read_failure_commits_provider_error_with_partial_usage(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    asynchronous: bool,
) -> None:
    import httpx

    class BrokenStream(Stream):
        def __next__(self) -> Any:
            raise httpx.ReadError("synthetic reset after send")

        async def __anext__(self) -> Any:
            raise httpx.ReadError("synthetic reset after send")

    fake = FakeKaiten()
    raw = BrokenStream([])
    provider = Provider(raw, asynchronous)

    async def scenario() -> None:
        client, _ = make_async_client(fake)
        async with client:
            stream = await wrap_openai(
                provider, kaiten=client, instance="i", entitlement="p"
            ).responses.create(model="m", stream=True)
            with pytest.raises(httpx.ReadError):
                await stream.__anext__()

    if asynchronous:
        asyncio.run(scenario())
    else:
        client, _ = make_client(fake)
        with client:
            stream = wrap_openai(
                provider, kaiten=client, instance="i", entitlement="p"
            ).responses.create(model="m", stream=True)
            with pytest.raises(httpx.ReadError):
                next(stream)
            stream.close()
    assert len(fake.commits) == 1
    assert fake.commits[0]["requestStatus"] == "PROVIDER_ERROR"


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
@pytest.mark.parametrize("drop_in_client", [False, True])
@pytest.mark.parametrize("include_entitlement", [False, True])
def test_provider_entry_points_reject_pool_before_constructing_or_calling_provider(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
    asynchronous: bool,
    provider_name: str,
    drop_in_client: bool,
    include_entitlement: bool,
) -> None:
    from kaitencloud._provider_clients import drop_in

    fake = FakeKaiten()
    factory = make_async_client if asynchronous else make_client
    client, _ = factory(fake)
    options: dict[str, Any] = {"kaiten": client, "instance": "i", "pool": "p"}
    if include_entitlement:
        options["entitlement"] = "p"
    if drop_in_client:
        name = ("Async" if asynchronous else "") + (
            "OpenAI" if provider_name == "openai" else "Anthropic"
        )

        class Base:
            def __init__(self, **kwargs: Any) -> None:
                pytest.fail("provider must not be constructed")

        monkeypatch.setitem(sys.modules, provider_name, SimpleNamespace(**{name: Base}))
        target = drop_in(provider_name, name, f"kaitencloud.{provider_name}")
        args = ()
    else:
        target = wrap_openai if provider_name == "openai" else wrap_anthropic
        args = (Provider("reply", asynchronous),)
    with pytest.raises(TypeError, match="pool"):
        target(*args, **options)
    assert fake.reports == []
    if asynchronous:
        asyncio.run(client.close())
    else:
        client.close()
