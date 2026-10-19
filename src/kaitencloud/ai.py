# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""AI credits: meter every model call against an instance's AI credit pool.

Kaiten prices AI usage on the server, with the conversion rules of the instance's license; the
SDK only says what was used. Each call is one operation in two phases, paired by a transaction
id: a **reservation** of the call's estimate before it -- refused when the pool cannot cover
it -- and a **commit** of its real usage after it.

The provider wrappers do all of this with one changed line::

    from kaitencloud.openai import OpenAI      # instead of: from openai import OpenAI

    openai = OpenAI(kaiten=kaiten, instance="acme-prod", entitlement="chat-credits")

Anything else goes through :func:`run`, which reserves, calls, and commits::

    from kaitencloud import ai

    reply = ai.run(
        kaiten,
        lambda: llm.generate(prompt),
        instance="acme-prod",
        entitlement="chat-credits",
        model="gpt-4o",
        estimate={"input_tokens": 1200, "output_tokens": 800},
        usage=lambda reply: ai.from_openai(reply.usage),
    )

or through the phases themselves, :func:`reserve` and :func:`commit`. With an
:class:`~kaitencloud.AsyncKaitenClient`, the same functions return awaitables and ``fn`` is a
coroutine function.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar, overload

from ._ai import (
    AiRequest,
    Estimator,
    UsageOf,
    add_usage,
    default_estimator,
    from_anthropic,
    from_openai,
    new_transaction_id,
    request_status_of,
)
from ._ai_models import AiCredits, AiEntitlementUsage, AiUsageOutcome
from ._async.ai import AsyncMeter, async_run
from ._async.client import AsyncKaitenClient
from ._exceptions import (
    AiUsageUnsupportedError,
    InsufficientCreditsError,
    ModelNotAuthorizedError,
    TransactionIdReusedError,
    UnknownModelError,
)
from ._sync.ai import Meter
from ._sync.ai import run as sync_run
from ._sync.client import KaitenClient
from .types import AiRequestStatus, AiRequestType, AiUnitType, AiUsageParam

__all__ = [
    "AiCredits",
    "AiEntitlementUsage",
    "AiRequest",
    "AiRequestStatus",
    "AiRequestType",
    "AiUnitType",
    "AiUsageOutcome",
    "AiUsageParam",
    "AiUsageUnsupportedError",
    "AsyncMeter",
    "Estimator",
    "InsufficientCreditsError",
    "Meter",
    "ModelNotAuthorizedError",
    "TransactionIdReusedError",
    "UnknownModelError",
    "UsageOf",
    "add_usage",
    "commit",
    "default_estimator",
    "from_anthropic",
    "from_openai",
    "new_transaction_id",
    "request_status_of",
    "reserve",
    "run",
]

T = TypeVar("T")


@overload
def reserve(
    kaiten: KaitenClient,
    *,
    instance: str,
    entitlement: str,
    model: str,
    request_type: AiRequestType = ...,
    usage: AiUsageParam | None = ...,
    transaction_id: str | None = ...,
    ttl_seconds: int | None = ...,
) -> AiEntitlementUsage: ...
@overload
def reserve(
    kaiten: AsyncKaitenClient,
    *,
    instance: str,
    entitlement: str,
    model: str,
    request_type: AiRequestType = ...,
    usage: AiUsageParam | None = ...,
    transaction_id: str | None = ...,
    ttl_seconds: int | None = ...,
) -> Coroutine[Any, Any, AiEntitlementUsage]: ...
def reserve(
    kaiten: KaitenClient | AsyncKaitenClient,
    *,
    instance: str,
    entitlement: str,
    model: str,
    request_type: AiRequestType = "COMPLETION",
    usage: AiUsageParam | None = None,
    transaction_id: str | None = None,
    ttl_seconds: int | None = None,
) -> AiEntitlementUsage | Coroutine[Any, Any, AiEntitlementUsage]:
    """Reserve the credits a call is expected to cost; see ``instances.reserve_ai_usage``.

    The transaction id to commit under is the answer's ``ai.transaction_id`` -- a fresh UUIDv7
    unless ``transaction_id`` is given.
    """
    return kaiten.instances.reserve_ai_usage(
        instance,
        entitlement,
        model=model,
        request_type=request_type,
        usage=usage,
        transaction_id=transaction_id,
        ttl_seconds=ttl_seconds,
    )


@overload
def commit(
    kaiten: KaitenClient,
    *,
    instance: str,
    entitlement: str,
    transaction_id: str,
    request_status: AiRequestStatus = ...,
    usage: AiUsageParam | None = ...,
    model: str | None = ...,
    request_type: AiRequestType | None = ...,
) -> AiEntitlementUsage: ...
@overload
def commit(
    kaiten: AsyncKaitenClient,
    *,
    instance: str,
    entitlement: str,
    transaction_id: str,
    request_status: AiRequestStatus = ...,
    usage: AiUsageParam | None = ...,
    model: str | None = ...,
    request_type: AiRequestType | None = ...,
) -> Coroutine[Any, Any, AiEntitlementUsage]: ...
def commit(
    kaiten: KaitenClient | AsyncKaitenClient,
    *,
    instance: str,
    entitlement: str,
    transaction_id: str,
    request_status: AiRequestStatus = "SUCCESS",
    usage: AiUsageParam | None = None,
    model: str | None = None,
    request_type: AiRequestType | None = None,
) -> AiEntitlementUsage | Coroutine[Any, Any, AiEntitlementUsage]:
    """Charge what a call really consumed; see ``instances.commit_ai_usage``.

    ``request_status="NOT_SENT"`` releases a reservation whose call never reached the provider.
    """
    return kaiten.instances.commit_ai_usage(
        instance,
        entitlement,
        transaction_id=transaction_id,
        request_status=request_status,
        usage=usage,
        model=model,
        request_type=request_type,
    )


@overload
def run(
    kaiten: KaitenClient,
    fn: Callable[[], T],
    *,
    instance: str,
    entitlement: str,
    model: str,
    request_type: AiRequestType = ...,
    estimate: AiUsageParam | None = ...,
    usage: UsageOf | None = ...,
    transaction_id: str | None = ...,
    ttl_seconds: int | None = ...,
) -> T: ...
@overload
def run(
    kaiten: AsyncKaitenClient,
    fn: Callable[[], Awaitable[T]],
    *,
    instance: str,
    entitlement: str,
    model: str,
    request_type: AiRequestType = ...,
    estimate: AiUsageParam | None = ...,
    usage: UsageOf | None = ...,
    transaction_id: str | None = ...,
    ttl_seconds: int | None = ...,
) -> Coroutine[Any, Any, T]: ...
def run(
    kaiten: KaitenClient | AsyncKaitenClient,
    fn: Callable[[], Any],
    *,
    instance: str,
    entitlement: str,
    model: str,
    request_type: AiRequestType = "COMPLETION",
    estimate: AiUsageParam | None = None,
    usage: UsageOf | None = None,
    transaction_id: str | None = None,
    ttl_seconds: int | None = None,
) -> Any:
    """Reserve ``estimate``, call ``fn``, commit what it used, and return what ``fn`` returned.

    Args:
        kaiten: The client to report through. With an async client, ``fn`` is a coroutine
            function and ``run`` returns an awaitable.
        fn: The provider call, taking no argument.
        instance: The instance making the call.
        entitlement: The slug of the AI credit entitlement it draws on.
        model: The model, as a catalogue slug or a provider id.
        request_type: What the call produces; ``"COMPLETION"`` by default.
        estimate: The usage to reserve.
        usage: Reads the real usage out of ``fn``'s result, e.g. with :func:`from_openai`.
        transaction_id: The operation's id; a fresh UUIDv7 by default.
        ttl_seconds: How long the reservation holds; the server's default otherwise.

    Raises:
        InsufficientCreditsError: The pool cannot cover the estimate. ``fn`` was not called.
        UnknownModelError: The model is not in the catalogue. ``fn`` was not called.
        ModelNotAuthorizedError: No rule prices the model. ``fn`` was not called.

    When ``fn`` raises, the commit records how the call ended -- ``PROVIDER_ERROR``,
    ``CUSTOMER_ERROR``, or ``NOT_SENT`` when it never reached the provider -- and the error
    propagates. A commit that fails is logged, never raised: the call already happened. A
    deployment without AI credits is logged once and ``fn`` runs unmetered.
    """
    options: dict[str, Any] = {
        "instance": instance,
        "entitlement": entitlement,
        "model": model,
        "request_type": request_type,
        "estimate": estimate,
        "usage": usage,
        "transaction_id": transaction_id,
        "ttl_seconds": ttl_seconds,
    }
    if isinstance(kaiten, AsyncKaitenClient):
        return async_run(kaiten, fn, **options)
    return sync_run(kaiten, fn, **options)
