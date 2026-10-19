# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Pinned optional provider SDKs, driven entirely by in-process mock transports."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest
from ai_fakes import FakeKaiten


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_real_drop_in_and_copy_use_mock_transports(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    asynchronous: bool,
    provider: str,
) -> None:
    sdk = pytest.importorskip(provider)
    httpx2 = pytest.importorskip("httpx2")
    fake = FakeKaiten()
    calls = []
    if provider == "openai":
        payload = {
            "id": "r",
            "object": "chat.completion",
            "created": 1,
            "model": "m",
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        }
    else:
        payload = {
            "id": "r",
            "type": "message",
            "role": "assistant",
            "model": "m",
            "content": [],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 2},
        }

    def handler(request: Any) -> Any:
        calls.append(json.loads(request.content))
        return httpx2.Response(200, json=payload)

    import kaitencloud.anthropic as anthropic_module
    import kaitencloud.openai as openai_module

    module = openai_module if provider == "openai" else anthropic_module
    name = ("Async" if asynchronous else "") + ("OpenAI" if provider == "openai" else "Anthropic")
    cls = getattr(module, name)

    async def scenario() -> None:
        kaiten, _ = make_async_client(fake)
        async with (
            kaiten,
            cls(
                api_key="synthetic",
                kaiten=kaiten,
                instance="i",
                pool="p",
                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
            ) as client,
        ):
            copied = client.with_options(timeout=2)
            method = (
                copied.chat.completions.create if provider == "openai" else copied.messages.create
            )
            await method(model="m", messages=[], max_tokens=3)

    if asynchronous:
        asyncio.run(scenario())
    else:
        kaiten, _ = make_client(fake)
        with (
            kaiten,
            cls(
                api_key="synthetic",
                kaiten=kaiten,
                instance="i",
                pool="p",
                http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
            ) as client,
        ):
            assert isinstance(client, getattr(sdk, name))
            copied = client.with_options(timeout=2)
            method = (
                copied.chat.completions.create if provider == "openai" else copied.messages.create
            )
            method(model="m", messages=[], max_tokens=3)
    assert len(calls) == 1
    assert len(fake.reserves) == len(fake.commits) == 1
    assert fake.commits[0]["usage"] == {"inputTokens": 10, "outputTokens": 2}


@pytest.mark.parametrize("asynchronous", [False, True])
def test_real_anthropic_text_stream_does_not_duplicate_text(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    asynchronous: bool,
) -> None:
    pytest.importorskip("anthropic")
    httpx2 = pytest.importorskip("httpx2")
    from kaitencloud.anthropic import Anthropic, AsyncAnthropic

    fake = FakeKaiten()
    events = [
        {
            "type": "message_start",
            "message": {
                "id": "r",
                "type": "message",
                "role": "assistant",
                "model": "m",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 1},
            },
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "hello"},
        },
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 2},
        },
        {"type": "message_stop"},
    ]
    sse = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)

    def handler(request: Any) -> Any:
        return httpx2.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    async def scenario() -> str:
        kaiten, _ = make_async_client(fake)
        async with (
            kaiten,
            AsyncAnthropic(
                api_key="synthetic",
                kaiten=kaiten,
                instance="i",
                pool="p",
                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
            ) as client,
            client.messages.stream(model="m", max_tokens=3, messages=[]) as stream,
        ):
            text = "".join([part async for part in stream.text_stream])
            assert (await stream.get_final_message()).usage.output_tokens == 2
            return text

    if asynchronous:
        text = asyncio.run(scenario())
    else:
        kaiten, _ = make_client(fake)
        with (
            kaiten,
            Anthropic(
                api_key="synthetic",
                kaiten=kaiten,
                instance="i",
                pool="p",
                http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
            ) as client,
            client.messages.stream(model="m", max_tokens=3, messages=[]) as stream,
        ):
            text = "".join(stream.text_stream)
            assert stream.get_final_message().usage.output_tokens == 2
    assert text == "hello"
    assert len(fake.commits) == 1
    assert fake.commits[0]["usage"] == {"inputTokens": 10, "outputTokens": 2}


@pytest.mark.parametrize("asynchronous", [False, True])
def test_real_openai_chat_stream_reports_final_usage(
    make_client: Callable[..., Any],
    make_async_client: Callable[..., Any],
    asynchronous: bool,
) -> None:
    pytest.importorskip("openai")
    httpx2 = pytest.importorskip("httpx2")
    from kaitencloud.openai import AsyncOpenAI, OpenAI

    fake = FakeKaiten()
    chunks = [
        {
            "id": "r",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "m",
            "choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": None}],
            "usage": None,
        },
        {
            "id": "r",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "m",
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        },
    ]
    sse = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"

    def handler(request: Any) -> Any:
        assert json.loads(request.content)["stream_options"]["include_usage"] is True
        return httpx2.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    async def scenario() -> None:
        kaiten, _ = make_async_client(fake)
        async with (
            kaiten,
            AsyncOpenAI(
                api_key="synthetic",
                kaiten=kaiten,
                instance="i",
                pool="p",
                http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
            ) as client,
        ):
            stream = await client.chat.completions.create(model="m", messages=[], stream=True)
            async with stream:
                received = [chunk async for chunk in stream]
                assert received[0].choices[0].delta.content == "hello"

    if asynchronous:
        asyncio.run(scenario())
    else:
        kaiten, _ = make_client(fake)
        with (
            kaiten,
            OpenAI(
                api_key="synthetic",
                kaiten=kaiten,
                instance="i",
                pool="p",
                http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
            ) as client,
        ):
            stream = client.chat.completions.create(model="m", messages=[], stream=True)
            with stream:
                received = list(stream)
                assert received[0].choices[0].delta.content == "hello"
    assert len(fake.commits) == 1
    assert fake.commits[0]["usage"] == {"inputTokens": 10, "outputTokens": 2}
