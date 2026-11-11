# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Every error the SDK raises, rooted at :class:`KaitenError`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import ValidationError

from .types import ErrorDetail, Problem

__all__ = [
    "APIConnectionError",
    "APIResponseValidationError",
    "APIStatusError",
    "APITimeoutError",
    "AiCommitFailedError",
    "AiInferenceNotCommittedError",
    "AiInferenceNotFoundError",
    "AiPoolNotFoundError",
    "AiPoolNotGrantedError",
    "AiUsageDisabledError",
    "AiUsageUnsupportedError",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "CredentialError",
    "IdempotencyKeyReusedError",
    "InsufficientCreditsError",
    "InternalServerError",
    "InvalidIdempotencyKeyError",
    "InvalidRefundError",
    "KaitenError",
    "ModelNotAuthorizedError",
    "NotFoundError",
    "NothingToRefundError",
    "PaginationError",
    "PermissionDeniedError",
    "RateLimitError",
    "RefundExceedsRefundableError",
    "ServiceUnavailableError",
    "ThresholdExceededError",
    "TransactionIdReusedError",
    "UnknownModelError",
    "UnprocessableEntityError",
    "WebhookPayloadError",
    "WebhookVerificationError",
]


class KaitenError(Exception):
    """Base class of every error the SDK raises."""


class CredentialError(KaitenError, ValueError):
    """A credential is missing, or belongs to a class the target API refuses.

    Raised before anything is sent: a platform credential (``ksm_...``) handed to the Core
    client, an organization token handed to the platform client, or a webhook signing secret
    (``whsec_...``) handed to either.
    """


class APIConnectionError(KaitenError):
    """The request did not reach the API, or its response never came back."""

    def __init__(
        self, message: str = "Could not reach the Kaiten API.", *, request: httpx.Request
    ) -> None:
        super().__init__(message)
        self.request = request


class APITimeoutError(APIConnectionError):
    """The request timed out."""

    def __init__(self, *, request: httpx.Request) -> None:
        super().__init__("The request to the Kaiten API timed out.", request=request)


class APIResponseValidationError(KaitenError):
    """A successful response does not have the shape the contract promises."""

    def __init__(self, message: str, *, response: httpx.Response) -> None:
        super().__init__(message)
        self.response = response


class PaginationError(KaitenError):
    """A list endpoint reported more rows without a usable cursor to reach them.

    Raised instead of returning the rows fetched so far: a partial list handed back as a
    complete one is the one failure a caller has no way to notice.
    """


class APIStatusError(KaitenError):
    """The API answered with a non-2xx status.

    Branch on :attr:`code` where the API provides one, rather than on the status or the
    message: a 409 for a reached limit and a 409 for a taken slug share a status, not a meaning.
    """

    def __init__(self, message: str, *, response: httpx.Response, problem: Problem | None) -> None:
        super().__init__(message)
        self.response = response
        self.status_code = response.status_code
        self.problem = problem

    @property
    def request(self) -> httpx.Request:
        """The request that failed."""
        return self.response.request

    @property
    def code(self) -> str | None:
        """The stable, machine-readable error code, e.g. ``"License.NotFound"``, when sent."""
        return self.problem.code if self.problem else None

    @property
    def title(self) -> str | None:
        """The short summary of the problem."""
        return self.problem.title if self.problem else None

    @property
    def detail(self) -> str | None:
        """The explanation of this occurrence of the problem."""
        return self.problem.detail if self.problem else None

    @property
    def error_id(self) -> str | None:
        """The id of the server-side log entry holding the cause the API withheld.

        Quote it when reporting a bug: it is the only handle on the real error.
        """
        return self.problem.error_id if self.problem else None

    @property
    def errors(self) -> list[ErrorDetail]:
        """The individual validation errors, when the API listed them."""
        return list(self.problem.errors or []) if self.problem else []

    @property
    def body(self) -> str:
        """The raw response body."""
        return self.response.text


class BadRequestError(APIStatusError):
    """The API answered 400: the request is malformed."""


class AuthenticationError(APIStatusError):
    """The API answered 401: the credential is missing, invalid, expired or revoked."""


class PermissionDeniedError(APIStatusError):
    """The API answered 403: the credential lacks a scope, or its class is refused here."""


class NotFoundError(APIStatusError):
    """The API answered 404."""


class ConflictError(APIStatusError):
    """The API answered 409: a limit was reached, or the resource conflicts with another."""


class ThresholdExceededError(ConflictError):
    """A usage report would take usage past the maximum the license allows.

    That maximum is the grant's value plus its overage allowance. The report was refused and
    nothing was recorded.
    """


class UnprocessableEntityError(APIStatusError):
    """The API answered 422: the request is well-formed but its content is refused."""


class InsufficientCreditsError(ThresholdExceededError):
    """An AI usage reservation does not fit in what is left of the credit pool.

    Raised before the provider is called: nothing was reserved, and nothing is owed.
    """


class TransactionIdReusedError(ConflictError):
    """An AI usage transaction id was already used for another call.

    The same id and phase arrived with another body -- a retried commit whose ``vendor_cost``
    is spelled differently, ``"0.01"`` then ``"0.010"``, is another body -- or a reservation was
    made on an id that is already reserved or closed. A release of a transaction that never
    reserved (answered with the ``NO_RESERVATION`` warning) closes its id for good: a reserve or
    commit sent under it afterwards lands here too. A bug in the caller, never a transient
    failure: not retried.
    """


class ModelNotAuthorizedError(UnprocessableEntityError):
    """The model may not be reserved against: it is archived, or no conversion rule prices it."""


class UnknownModelError(UnprocessableEntityError):
    """The model is in neither the catalogue's slugs nor its provider ids."""


class AiUsageUnsupportedError(UnprocessableEntityError):
    """The API cannot take an AI usage report on this entitlement.

    Either the entitlement is not an AI credit pool aggregated by ``SUM`` -- a configuration
    error -- or the deployment predates AI credits, which ``GET /ai/capabilities`` answering
    404 proves. Never a reason to let a call through unmetered: the meters and the provider
    wrappers raise it on every call, before the provider is called.
    """


class AiUsageDisabledError(PermissionDeniedError):
    """AI credits are turned off on this Kaiten deployment (``AIUsage.Disabled``).

    Raised by every AI operation while the deployment's AI credits flag is off, before anything
    is recorded. ``instances.get_ai_capabilities()`` answers ``enabled=False`` meanwhile.
    """


class AiCommitFailedError(KaitenError):
    """A metered call ran, and its commit still failed after its retries.

    The call already happened; the cause is the :attr:`__cause__`. Unless the commit's answer
    was lost on the way back, nothing was charged, and the reservation will expire on its own.
    Settle it by sending the same commit again, :attr:`arguments` unchanged, through
    ``instances.commit_ai_usage(instance, entitlement, **arguments)``: an identical commit is
    applied once, however many times it is sent. A cause that is a refusal -- a 4xx, such as
    ``TransactionIdReusedError`` -- will be refused again: it is a bug to fix, not to retry.

    :attr:`result` holds what the metered call returned, so a caller that prefers serving the
    answer to failing the request can still do so. A meter given ``on_commit_failure`` hands
    this error to it instead of raising it.
    """

    def __init__(
        self,
        message: str,
        *,
        instance: str,
        entitlement: str,
        transaction_id: str,
        arguments: Mapping[str, Any],
        result: Any = None,
    ) -> None:
        super().__init__(message)
        self.instance = instance
        self.entitlement = entitlement
        self.transaction_id = transaction_id
        self.arguments: dict[str, Any] = dict(arguments)
        self.result = result


class AiPoolNotFoundError(NotFoundError):
    """No such instance, or the instance has no such AI credit pool (``*.ContextNotFound``)."""


class AiInferenceNotFoundError(NotFoundError):
    """The pool has no inference under this transaction id (``*.InferenceNotFound``)."""


class AiInferenceNotCommittedError(ConflictError):
    """Only a committed inference can be refunded: this one is reserved, released or expired."""


class NothingToRefundError(ConflictError):
    """The inference charged nothing, or was already refunded in full."""


class RefundExceedsRefundableError(ConflictError):
    """The refund asks for more credits than the inference has left to refund.

    :attr:`refundable` is what is left, as the API reports it, when it does.
    """

    @property
    def refundable(self) -> str | None:
        """The credits still refundable on the inference, as a decimal string."""
        for error in self.errors:
            if error.value is not None:
                return str(error.value)
        return None


class IdempotencyKeyReusedError(ConflictError):
    """The idempotency key was already spent on another refund, or on another request body.

    Send a new key for a new refund; resend the same key only with the same body.
    """


class AiPoolNotGrantedError(ConflictError):
    """The instance no longer holds the AI credit pool the inference was charged to."""


class InvalidRefundError(UnprocessableEntityError):
    """The refund's amount or reason is refused (``*.InvalidAmount``, ``*.InvalidReason``)."""


class InvalidIdempotencyKeyError(UnprocessableEntityError):
    """The idempotency key is missing or malformed: 1 to 128 of letters, digits and ``._:-``."""


class RateLimitError(APIStatusError):
    """The API answered 429."""


class InternalServerError(APIStatusError):
    """The API answered with a 5xx status."""


class ServiceUnavailableError(InternalServerError):
    """The API answered 503.

    Kaiten answers 503 when it cannot verify a limit a creation is subject to: it refuses the
    creation rather than let through one the plan might not allow.
    """


class WebhookVerificationError(KaitenError):
    """A webhook delivery failed verification: answer 400 and do not act on it."""


class WebhookPayloadError(KaitenError):
    """A verified webhook payload does not match the event contract it names."""


_STATUS_ERRORS: Mapping[int, type[APIStatusError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    422: UnprocessableEntityError,
    429: RateLimitError,
    503: ServiceUnavailableError,
}


def make_status_error(
    response: httpx.Response,
    *,
    overrides: Mapping[int, type[APIStatusError]] | None = None,
) -> APIStatusError:
    """Build the error for a non-2xx ``response``."""
    status = response.status_code
    error_class = (overrides or {}).get(status) or _STATUS_ERRORS.get(status)
    if error_class is None:
        error_class = InternalServerError if status >= 500 else APIStatusError
    problem = parse_problem(response)
    return error_class(_message(response, problem), response=response, problem=problem)


AI_DISABLED_CODE = "AIUsage.Disabled"
"""The code every AI operation answers, with a 403, while AI credits are turned off."""

# The typed error of an AI answer, by status and by the last segment of its code. Only codes
# the API documents are here: an unknown code stays the plain status error, never a guess.
_AI_ERRORS: Mapping[tuple[int, str], type[APIStatusError]] = {
    (404, "ContextNotFound"): AiPoolNotFoundError,
    (409, "ThresholdExceeded"): InsufficientCreditsError,
    (409, "TransactionIdReused"): TransactionIdReusedError,
    (422, "UnknownModel"): UnknownModelError,
    (422, "ModelNotAuthorized"): ModelNotAuthorizedError,
    (422, "AiUsageUnsupportedEntitlement"): AiUsageUnsupportedError,
}

# The refund's own codes, ``RefundAiInference.<reason>``.
_REFUND_ERRORS: Mapping[tuple[int, str], type[APIStatusError]] = {
    (404, "ContextNotFound"): AiPoolNotFoundError,
    (404, "InferenceNotFound"): AiInferenceNotFoundError,
    (409, "NotCommitted"): AiInferenceNotCommittedError,
    (409, "NothingToRefund"): NothingToRefundError,
    (409, "ExceedsRefundable"): RefundExceedsRefundableError,
    (409, "IdempotencyKeyReused"): IdempotencyKeyReusedError,
    (409, "PoolNotGranted"): AiPoolNotGrantedError,
    (422, "IdempotencyKeyRequired"): InvalidIdempotencyKeyError,
    (422, "InvalidIdempotencyKey"): InvalidIdempotencyKeyError,
    (422, "InvalidAmount"): InvalidRefundError,
    (422, "InvalidReason"): InvalidRefundError,
}


def make_ai_error(error: APIStatusError) -> APIStatusError:
    """The typed error an AI operation answered with ``error`` stands for.

    The status alone does not say it: a 409 is a full pool or a reused transaction id, and a
    422 is a refused model, a malformed body or an entitlement that is not an AI credit pool.
    A 403 ``AIUsage.Disabled`` is the deployment's AI credits being off. An unknown code is
    returned as it is: it is never read as "AI credits are unsupported here".
    """
    code = error.code or ""
    if error.status_code == 403 and code == AI_DISABLED_CODE:
        target: type[APIStatusError] | None = AiUsageDisabledError
    else:
        operation, _, reason = code.rpartition(".")
        table = _REFUND_ERRORS if operation == "RefundAiInference" else _AI_ERRORS
        target = table.get((error.status_code, reason))
    if target is None:
        return error
    return target(str(error), response=error.response, problem=error.problem)


def parse_problem(response: httpx.Response) -> Problem | None:
    """The RFC 9457 problem in ``response``, or ``None`` when the body is not one.

    Only a problem that says something is kept: a proxy's HTML error page or an empty body is
    better reported raw than as a problem whose every field is empty.
    """
    try:
        data: Any = response.json()
    except ValueError:
        return None
    if not isinstance(data, dict) or not any(data.get(key) for key in ("title", "detail", "code")):
        return None
    try:
        return Problem.model_validate(data)
    except ValidationError:
        return None


def _message(response: httpx.Response, problem: Problem | None) -> str:
    reason = response.reason_phrase or httpx.codes.get_reason_phrase(response.status_code)
    prefix = f"Kaiten API error ({response.status_code} {reason})".replace(" )", ")")
    suffix = ""
    if problem is not None:
        if problem.code:
            prefix += f" [{problem.code}]"
        if problem.error_id:
            suffix = f" (errorId: {problem.error_id})"
        text = ": ".join(
            part.strip() for part in (problem.title, problem.detail) if part and part.strip()
        )
        if text:
            return f"{prefix}: {text}{suffix}"
    body = response.text.strip()
    if body:
        return f"{prefix}: {body[:500]}{suffix}"
    return prefix + suffix
