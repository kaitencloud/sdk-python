# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Reserve, call, commit: the loop every AI wrapper runs, for one instance and one pool."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from .._ai import (
    AiRequest,
    Estimator,
    UsageOf,
    VendorCost,
    VendorCostOf,
    ai_usage_body,
    default_estimator,
    new_transaction_id,
    request_status_of,
    vendor_cost_string,
)
from .._ai_models import AiEntitlementUsage
from .._exceptions import AiCommitFailedError, KaitenError
from .._utils import async_shielded
from ..types import AiRequestStatus, AiRequestType, AiUsageParam
from .client import AsyncKaitenClient

__all__ = ["AsyncMeter", "CommitFailureHandler", "async_run"]

T = TypeVar("T")

CommitFailureHandler = Callable[[AiCommitFailedError], None]
"""Receives a commit that failed after its retries, instead of it being raised."""

log = logging.getLogger("kaitencloud.ai")


class AsyncMeter:
    """Meters AI calls against one AI credit pool of one instance.

    Every call is one operation: :meth:`reserve` before it, :meth:`commit` after it, under one
    transaction id. A reservation the pool refuses raises its typed error, and the call must
    not be made. So does a reservation Kaiten cannot take at all -- an entitlement that is not
    an AI credit pool, a deployment without AI credits, AI credits turned off: the meter fails
    closed, on every call, and never lets one through unmetered.

    A commit that still fails after its retries raises :class:`AiCommitFailedError`, which
    carries the call's result and the commit to send again. Give ``on_commit_failure`` to
    receive it instead -- to queue the commit for later, say -- and serve the call's result.
    When the call itself failed, its own error is raised, and a failed commit goes to
    ``on_commit_failure``, or to the ``kaitencloud.ai`` log at ERROR.

    A commit runs to its end even when the task awaiting it is cancelled.
    """

    def __init__(
        self,
        kaiten: AsyncKaitenClient,
        *,
        instance: str,
        entitlement: str,
        estimator: Estimator | None = None,
        on_commit_failure: CommitFailureHandler | None = None,
    ) -> None:
        self.kaiten = kaiten
        self.instance = instance
        self.entitlement = entitlement
        self.estimator: Estimator = estimator or default_estimator
        self.on_commit_failure = on_commit_failure

    def __repr__(self) -> str:
        return (
            f"<{type(self).__name__} instance={self.instance!r} entitlement={self.entitlement!r}>"
        )

    def estimate(self, request: AiRequest) -> AiUsageParam | None:
        """The usage to reserve for ``request``, from the meter's estimator."""
        return self.estimator(request)

    async def reserve(
        self,
        *,
        model: str,
        request_type: AiRequestType = "COMPLETION",
        usage: AiUsageParam | None = None,
        transaction_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> str:
        """Reserve for one call and return its transaction id.

        Raises the reservation's typed error -- ``InsufficientCreditsError``,
        ``UnknownModelError``, ``ModelNotAuthorizedError``, ``AiUsageUnsupportedError``,
        ``AiUsageDisabledError`` -- or the transport's, and the call must not be made.
        """
        transaction_id = transaction_id or new_transaction_id()
        await self.kaiten.instances.reserve_ai_usage(
            self.instance,
            self.entitlement,
            model=model,
            request_type=request_type,
            transaction_id=transaction_id,
            usage=usage,
            ttl_seconds=ttl_seconds,
        )
        return transaction_id

    async def commit(
        self,
        transaction_id: str | None,
        *,
        request_status: AiRequestStatus = "SUCCESS",
        usage: AiUsageParam | None = None,
        model: str | None = None,
        request_type: AiRequestType | None = None,
        vendor_cost: VendorCost | None = None,
        result: Any = None,
    ) -> AiEntitlementUsage | None:
        """Commit one call, and return the answer; ``None`` when ``on_commit_failure`` took it.

        ``transaction_id`` is the reservation's. ``None`` -- a call that went unreserved --
        commits under a fresh id, with ``model`` and ``request_type`` naming what ran. An
        invalid ``usage`` or ``vendor_cost`` is logged and left out: the call is still settled.
        ``result`` is what the call returned, handed back on :class:`AiCommitFailedError`.

        Raises:
            AiCommitFailedError: The commit failed after its retries, and the meter has no
                ``on_commit_failure``.
        """
        if transaction_id is None:
            transaction_id = new_transaction_id()
        usage = self._valid_usage(transaction_id, usage)
        cost = (
            None if request_status == "NOT_SENT" else self._valid_cost(transaction_id, vendor_cost)
        )
        arguments: dict[str, Any] = {
            "transaction_id": transaction_id,
            "request_status": request_status,
            "usage": usage,
            "model": model,
            "request_type": request_type,
            "vendor_cost": cost,
        }
        try:
            return await async_shielded(
                self.kaiten.instances.commit_ai_usage(self.instance, self.entitlement, **arguments)
            )
        except (KaitenError, ValueError) as error:
            failure = AiCommitFailedError(
                f"Kaiten AI usage: the commit of transaction {transaction_id} on "
                f"{self.instance}/{self.entitlement} failed: {error}. Sending the same "
                "commit again is safe, and settles the call.",
                instance=self.instance,
                entitlement=self.entitlement,
                transaction_id=transaction_id,
                arguments=arguments,
                result=result,
            )
            failure.__cause__ = error
            if self.on_commit_failure is None:
                raise failure from error
            self.on_commit_failure(failure)
            return None

    async def release(self, transaction_id: str | None) -> AiEntitlementUsage | None:
        """Release a reservation whose call never reached the provider: nothing is charged.

        A transaction that never reserved is answered with the ``NO_RESERVATION`` warning, and
        its id is closed for good.
        """
        if transaction_id is None:
            return None
        return await self.commit(transaction_id, request_status="NOT_SENT")

    async def run(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        model: str,
        request_type: AiRequestType = "COMPLETION",
        estimate: AiUsageParam | None = None,
        usage: UsageOf | None = None,
        vendor_cost: VendorCost | VendorCostOf | None = None,
        transaction_id: str | None = None,
        ttl_seconds: int | None = None,
    ) -> T:
        """Reserve ``estimate``, call ``fn``, commit what it reports, and return its result.

        ``usage`` reads the consumption out of ``fn``'s result, and ``vendor_cost`` is what
        the call cost at its vendor: a value, or a function reading it out of the result.
        When ``fn`` raises -- or is cancelled -- the commit says how it ended
        (:func:`~kaitencloud.ai.request_status_of`) and the error propagates.
        """
        reserved = await self.reserve(
            model=model,
            request_type=request_type,
            usage=estimate,
            transaction_id=transaction_id,
            ttl_seconds=ttl_seconds,
        )
        try:
            result = await fn()
        except BaseException as error:
            await self.settle_failure(reserved, error)
            raise
        actual_usage = self._read(reserved, "usage extraction", "usage", usage, result)
        cost = (
            self._read(reserved, "the vendor cost function", "vendor cost", vendor_cost, result)
            if callable(vendor_cost)
            else vendor_cost
        )
        await self.commit(reserved, usage=actual_usage, vendor_cost=cost, result=result)
        return result

    async def settle_failure(
        self,
        transaction_id: str,
        error: BaseException,
        *,
        usage: AiUsageParam | None = None,
        request_status: AiRequestStatus | None = None,
    ) -> None:
        """Commit a call that raised ``error``, never masking it with the commit's own failure.

        A commit that fails is handed to ``on_commit_failure``, or logged at ERROR: the
        caller is about to see ``error``, which is what went wrong first.
        """
        try:
            await self.commit(
                transaction_id,
                request_status=request_status or request_status_of(error),
                usage=usage,
            )
        except AiCommitFailedError:
            log.exception(
                "Kaiten AI usage: the commit of failed transaction %s on %s/%s failed too; "
                "its reservation will expire and the call goes unbilled",
                transaction_id,
                self.instance,
                self.entitlement,
            )

    def _valid_usage(self, transaction_id: str, usage: AiUsageParam | None) -> AiUsageParam | None:
        if usage is None:
            return None
        try:
            ai_usage_body(usage)
        except ValueError:
            self._log_invalid("usage", transaction_id)
            return None
        return usage

    def _valid_cost(self, transaction_id: str, vendor_cost: VendorCost | None) -> str | None:
        """``vendor_cost`` spelled once, as every retry of this commit will send it."""
        if vendor_cost is None:
            return None
        try:
            return vendor_cost_string(vendor_cost)
        except ValueError:
            self._log_invalid("vendor cost", transaction_id)
            return None

    def _log_invalid(self, what: str, transaction_id: str) -> None:
        log.exception(
            "Kaiten AI usage: invalid %s for transaction %s on %s/%s; "
            "attempting settlement without %s",
            what,
            transaction_id,
            self.instance,
            self.entitlement,
            what,
        )

    def _read(self, transaction_id: str, what: str, missing: str, reader: Any, result: Any) -> Any:
        if reader is None:
            return None
        try:
            return reader(result)
        except Exception:
            log.exception(
                "Kaiten AI usage: %s for transaction %s on %s/%s failed; "
                "attempting settlement without %s",
                what,
                transaction_id,
                self.instance,
                self.entitlement,
                missing,
            )
            return None


async def async_run(
    kaiten: AsyncKaitenClient,
    fn: Callable[[], Awaitable[T]],
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
) -> T:
    """One metered call: see :meth:`AsyncMeter.run`."""
    meter = AsyncMeter(
        kaiten, instance=instance, entitlement=entitlement, on_commit_failure=on_commit_failure
    )
    return await meter.run(
        fn,
        model=model,
        request_type=request_type,
        estimate=estimate,
        usage=usage,
        vendor_cost=vendor_cost,
        transaction_id=transaction_id,
        ttl_seconds=ttl_seconds,
    )
