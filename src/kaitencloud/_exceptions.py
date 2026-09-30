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
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "CredentialError",
    "InternalServerError",
    "KaitenError",
    "NotFoundError",
    "PaginationError",
    "PermissionDeniedError",
    "RateLimitError",
    "ServiceUnavailableError",
    "ThresholdExceededError",
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
