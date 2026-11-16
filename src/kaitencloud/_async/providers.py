# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Allow-listed provider delegation and asynchronous stream settlement."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from types import TracebackType
from typing import Any

from .._ai import (
    AiRequest,
    ProviderVendorCostOf,
    VendorCost,
    ttl_from_timeout,
)
from .._provider_usage import ANTHROPIC_METHODS, OPENAI_METHODS, UsageSnapshot, get
from ..types import AiRequestStatus
from .ai import AsyncMeter

log = logging.getLogger("kaitencloud.ai")


class AsyncProvider:
    """A provider-owned client/resource, with only its bounded usage methods intercepted."""

    def __init__(
        self,
        client: Any,
        meter: AsyncMeter,
        provider: str,
        *,
        path: str = "",
        root: Any = None,
        vendor_cost: ProviderVendorCostOf | None = None,
    ) -> None:
        self._client = client
        self._meter = meter
        self._provider = provider
        self._path = path
        self._root = client if root is None else root
        self._methods = OPENAI_METHODS if provider == "openai" else ANTHROPIC_METHODS
        self._vendor_cost = vendor_cost

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._client, name)
        path = f"{self._path}.{name}" if self._path else name
        if not self._path and name in ("copy", "with_options"):

            def copy(*args: Any, **kwargs: Any) -> AsyncProvider:
                return AsyncProvider(
                    target(*args, **kwargs),
                    self._meter,
                    self._provider,
                    vendor_cost=self._vendor_cost,
                )

            return copy
        if path in self._methods:
            if path == "messages.stream":

                def manager(**kwargs: Any) -> AsyncProviderStreamManager:
                    return AsyncProviderStreamManager(self, target, path, kwargs)

                return manager

            async def call(**kwargs: Any) -> Any:
                request = self._request(path, kwargs)
                transaction = await self._reserve(request)
                if path == "chat.completions.create" and kwargs.get("stream"):
                    kwargs = {
                        **kwargs,
                        "stream_options": {
                            **(kwargs.get("stream_options") or {}),
                            "include_usage": True,
                        },
                    }
                try:
                    result = await target(**kwargs)
                except BaseException as error:
                    await self._meter.settle_failure(transaction, error)
                    raise
                snapshot = UsageSnapshot(self._provider, path)
                if kwargs.get("stream"):
                    return AsyncProviderStream(result, self, request, transaction, snapshot)
                try:
                    snapshot.result(result)
                except Exception:
                    log.exception(
                        "Kaiten AI usage: provider usage extraction failed; settling without usage"
                    )
                await self._meter.commit(
                    transaction,
                    usage=snapshot.usage,
                    vendor_cost=self.vendor_cost(request, snapshot.usage, result),
                    result=result,
                )
                return result

            return call
        if any(method.startswith(path + ".") for method in self._methods):
            return AsyncProvider(
                target,
                self._meter,
                self._provider,
                path=path,
                root=self._root,
                vendor_cost=self._vendor_cost,
            )
        return target

    def _request(self, path: str, kwargs: dict[str, Any]) -> AiRequest:
        model = kwargs.get("model")
        if not isinstance(model, str) or not model:
            raise ValueError("a metered provider call requires an explicit model")
        return AiRequest(self._provider, path, model, self._methods[path], kwargs)

    async def _reserve(self, request: AiRequest) -> str:
        return await self._meter.reserve(
            model=request.model,
            request_type=request.request_type,
            usage=self._meter.estimate(request),
            ttl_seconds=ttl_from_timeout(request.params.get("timeout", get(self._root, "timeout"))),
        )

    def vendor_cost(self, request: AiRequest, usage: Any, result: Any) -> VendorCost | None:
        """The call's vendor cost from the ``vendor_cost`` callback; ``None`` without one.

        A callback that raises is logged, and the call is settled without a vendor cost.
        """
        if self._vendor_cost is None:
            return None
        try:
            return self._vendor_cost(request, usage, result)
        except Exception:
            log.exception("Kaiten AI usage: the vendor cost callback failed; settling without it")
            return None

    async def __aenter__(self) -> AsyncProvider:
        await self._client.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Any:
        return await self._client.__aexit__(exc_type, exc, traceback)


class AsyncProviderStream:
    """Delegated stream, settled exactly once: when it ends, fails, or is closed.

    The stream exists only once the provider answered, so the request was sent: a stream closed
    before it completed -- before its first event, too -- is settled ``CUSTOMER_ERROR`` with
    the usage seen so far, never released as ``NOT_SENT``.
    """

    def __init__(
        self,
        stream: Any,
        provider: AsyncProvider,
        request: AiRequest,
        transaction: str,
        snapshot: UsageSnapshot,
    ) -> None:
        self._stream = stream
        self._iterator = stream.__aiter__()
        self._provider = provider
        self._meter = provider._meter
        self._request = request
        self._transaction = transaction
        self._snapshot = snapshot
        self._settled = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)

    def __aiter__(self) -> AsyncIterator[Any]:
        return self

    async def __anext__(self) -> Any:
        try:
            event = await self._iterator.__anext__()
        except StopAsyncIteration:
            await self._settle("PROVIDER_ERROR" if self._snapshot.failed else "SUCCESS")
            raise
        except BaseException as error:
            if not self._settled:
                self._settled = True
                await self._meter.settle_failure(
                    self._transaction, error, usage=self._snapshot.usage
                )
            raise
        try:
            self._snapshot.event(event)
        except Exception:
            log.exception("Kaiten AI usage: stream usage extraction failed; keeping known usage")
        if self._snapshot.completed:
            await self._settle("PROVIDER_ERROR" if self._snapshot.failed else "SUCCESS")
        return event

    async def _settle(self, status: AiRequestStatus) -> None:
        if not self._settled:
            self._settled = True
            await self._meter.commit(
                self._transaction,
                request_status=status,
                usage=self._snapshot.usage,
                vendor_cost=self._provider.vendor_cost(self._request, self._snapshot.usage, None),
            )

    async def close(self) -> None:
        try:
            await self._stream.close()
        finally:
            await self._settle("SUCCESS" if self._snapshot.completed else "CUSTOMER_ERROR")

    async def __aenter__(self) -> AsyncProviderStream:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc is None:
            await self.close()
            return
        # Leaving on an error: settle it as one, and let that error be the one raised.
        try:
            await self._stream.close()
        finally:
            if not self._settled:
                self._settled = True
                await self._meter.settle_failure(
                    self._transaction,
                    exc,
                    usage=self._snapshot.usage,
                    request_status="SUCCESS" if self._snapshot.completed else None,
                )

    @property
    def text_stream(self) -> AsyncIterator[str]:
        async def texts() -> AsyncIterator[str]:
            async for event in self:
                kind = get(event, "type")
                delta = get(event, "delta")
                if kind == "text":
                    yield get(event, "text", "")
                elif (
                    self._snapshot.operation != "messages.stream"
                    and kind == "content_block_delta"
                    and get(delta, "type") == "text_delta"
                ):
                    yield get(delta, "text", "")

        return texts()

    async def until_done(self) -> None:
        async for _ in self:
            pass

    async def get_final_message(self) -> Any:
        await self.until_done()
        return await self._stream.get_final_message()

    async def get_final_text(self) -> str:
        message = await self.get_final_message()
        return "".join(get(block, "text", "") for block in get(message, "content", []))


class AsyncProviderStreamManager:
    """Anthropic's stream factory is synchronous, opening the network on async entry."""

    def __init__(
        self, provider: AsyncProvider, target: Callable[..., Any], path: str, kwargs: dict[str, Any]
    ) -> None:
        self._provider = provider
        self._target = target
        self._path = path
        self._kwargs = kwargs
        self._manager: Any = None
        self._stream: AsyncProviderStream | None = None

    async def __aenter__(self) -> Any:
        request = self._provider._request(self._path, self._kwargs)
        transaction = await self._provider._reserve(request)
        try:
            self._manager = self._target(**self._kwargs)
            stream = await self._manager.__aenter__()
        except BaseException as error:
            await self._provider._meter.settle_failure(transaction, error)
            raise
        self._stream = AsyncProviderStream(
            stream, self._provider, request, transaction, UsageSnapshot("anthropic", self._path)
        )
        return self._stream

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Any:
        try:
            return await self._manager.__aexit__(exc_type, exc, traceback)
        finally:
            if self._stream is not None:
                await self._stream.__aexit__(exc_type, exc, traceback)
