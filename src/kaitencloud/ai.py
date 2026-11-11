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

or through the phases themselves, :func:`reserve`, :func:`commit` and :func:`release`. With an
:class:`~kaitencloud.AsyncKaitenClient`, the same functions return awaitables and ``fn`` is a
coroutine function.

Metering fails closed. A reservation Kaiten refuses -- an empty pool, an unknown model, an
entitlement that is not an AI credit pool, a deployment without AI credits or with them turned
off -- raises, and the call is not made. A commit that still fails after its retries raises
:class:`AiCommitFailedError`, which carries the call's result and the commit to send again,
unless the meter was given ``on_commit_failure``.

A commit may carry the call's ``vendor_cost``: what it cost at the vendor, in USD, which Kaiten
records beside the cost it computes from the model catalogue. The SDK never computes a price:
pass a value, or a function that reads it out of the call's result.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar, overload

from ._ai import (
    AI_WARNINGS,
    AiRequest,
    AiWarning,
    Estimator,
    ProviderVendorCostOf,
    UsageOf,
    VendorCost,
    VendorCostOf,
    add_usage,
    default_estimator,
    from_anthropic,
    from_openai,
    new_transaction_id,
    request_status_of,
    vendor_cost_string,
)
from ._ai_models import (
    AiCredits,
    AiEntitlementUsage,
    AiInference,
    AiInferencePricing,
    AiInferenceRefund,
    AiUsageOutcome,
    AiUsageRule,
    AiVendorCost,
    OrganizationAiInference,
)
from ._async.ai import AsyncMeter, CommitFailureHandler, async_run
from ._async.client import AsyncKaitenClient
from ._exceptions import (
    AiCommitFailedError,
    AiUsageDisabledError,
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
    "AI_WARNINGS",
    "AiCommitFailedError",
    "AiCredits",
    "AiEntitlementUsage",
    "AiInference",
    "AiInferencePricing",
    "AiInferenceRefund",
    "AiRequest",
    "AiRequestStatus",
    "AiRequestType",
    "AiUnitType",
    "AiUsageDisabledError",
    "AiUsageOutcome",
    "AiUsageParam",
    "AiUsageRule",
    "AiUsageUnsupportedError",
    "AiVendorCost",
    "AiWarning",
    "AsyncMeter",
    "CommitFailureHandler",
    "Estimator",
    "InsufficientCreditsError",
    "Meter",
    "ModelNotAuthorizedError",
    "OrganizationAiInference",
    "ProviderVendorCostOf",
    "TransactionIdReusedError",
    "UnknownModelError",
    "UsageOf",
    "VendorCost",
    "VendorCostOf",
    "add_usage",
    "commit",
    "default_estimator",
    "from_anthropic",
    "from_openai",
    "new_transaction_id",
    "release",
    "request_status_of",
    "reserve",
    "run",
    "vendor_cost_string",
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
    vendor_cost: VendorCost | None = ...,
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
    vendor_cost: VendorCost | None = ...,
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
    vendor_cost: VendorCost | None = None,
) -> AiEntitlementUsage | Coroutine[Any, Any, AiEntitlementUsage]:
    """Charge what a call really consumed; see ``instances.commit_ai_usage``.

    ``vendor_cost`` is what the call cost at its vendor, sent exactly as spelled
    (:func:`vendor_cost_string`): send a commit again with the same string. A release is
    :func:`release`.
    """
    return kaiten.instances.commit_ai_usage(
        instance,
        entitlement,
        transaction_id=transaction_id,
        request_status=request_status,
        usage=usage,
        model=model,
        request_type=request_type,
        vendor_cost=vendor_cost,
    )


@overload
def release(
    kaiten: KaitenClient, *, instance: str, entitlement: str, transaction_id: str
) -> AiEntitlementUsage: ...
@overload
def release(
    kaiten: AsyncKaitenClient, *, instance: str, entitlement: str, transaction_id: str
) -> Coroutine[Any, Any, AiEntitlementUsage]: ...
def release(
    kaiten: KaitenClient | AsyncKaitenClient,
    *,
    instance: str,
    entitlement: str,
    transaction_id: str,
) -> AiEntitlementUsage | Coroutine[Any, Any, AiEntitlementUsage]:
    """Release a reservation whose call never reached the provider: nothing is charged.

    A commit with ``request_status="NOT_SENT"``, answered ``RELEASED``. Releasing a transaction
    that never reserved is answered ``RELEASED`` too, with the ``NO_RESERVATION`` warning in
    ``ai.warnings``, and closes the transaction id for good: a reserve or a commit sent under it
    afterwards raises :class:`TransactionIdReusedError`.
    """
    return kaiten.instances.commit_ai_usage(
        instance, entitlement, transaction_id=transaction_id, request_status="NOT_SENT"
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
    vendor_cost: VendorCost | VendorCostOf | None = ...,
    transaction_id: str | None = ...,
    ttl_seconds: int | None = ...,
    on_commit_failure: CommitFailureHandler | None = ...,
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
    vendor_cost: VendorCost | VendorCostOf | None = ...,
    transaction_id: str | None = ...,
    ttl_seconds: int | None = ...,
    on_commit_failure: CommitFailureHandler | None = ...,
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
    vendor_cost: VendorCost | VendorCostOf | None = None,
    transaction_id: str | None = None,
    ttl_seconds: int | None = None,
    on_commit_failure: CommitFailureHandler | None = None,
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
        vendor_cost: What the call cost at its vendor, in USD: a ``Decimal``, a decimal string
            or an int, or a function reading it out of ``fn``'s result. Never computed by the
            SDK; left out when the function raises or returns ``None``.
        transaction_id: The operation's id; a fresh UUIDv7 by default.
        ttl_seconds: How long the reservation holds; the server's default otherwise.
        on_commit_failure: Receives a commit that failed after its retries, instead of
            ``run`` raising it.

    Raises:
        InsufficientCreditsError: The pool cannot cover the estimate. ``fn`` was not called.
        UnknownModelError: The model is not in the catalogue. ``fn`` was not called.
        ModelNotAuthorizedError: No rule prices the model. ``fn`` was not called.
        AiUsageUnsupportedError: The entitlement is not an AI credit pool, or the deployment
            predates AI credits. ``fn`` was not called.
        AiUsageDisabledError: AI credits are turned off. ``fn`` was not called.
        AiCommitFailedError: ``fn`` ran, and its commit failed after its retries; the error's
            ``result`` is what ``fn`` returned.

    When ``fn`` raises -- or its task is cancelled -- the commit records how the call ended
    (``PROVIDER_ERROR``, ``CUSTOMER_ERROR``, or ``NOT_SENT`` when it never reached the
    provider) and ``fn``'s error propagates; a commit failing then is logged, never raised over
    it.
    """
    options: dict[str, Any] = {
        "instance": instance,
        "entitlement": entitlement,
        "model": model,
        "request_type": request_type,
        "estimate": estimate,
        "usage": usage,
        "vendor_cost": vendor_cost,
        "transaction_id": transaction_id,
        "ttl_seconds": ttl_seconds,
        "on_commit_failure": on_commit_failure,
    }
    if isinstance(kaiten, AsyncKaitenClient):
        return async_run(kaiten, fn, **options)
    return sync_run(kaiten, fn, **options)
