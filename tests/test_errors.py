# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Every failure becomes a typed error that keeps what the API said."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from helpers import respond

from kaitencloud import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    CredentialError,
    InternalServerError,
    KaitenError,
    NotFoundError,
    PaginationError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    ThresholdExceededError,
    UnprocessableEntityError,
    WebhookPayloadError,
    WebhookVerificationError,
)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, BadRequestError),
        (401, AuthenticationError),
        (403, PermissionDeniedError),
        (404, NotFoundError),
        (409, ConflictError),
        (418, APIStatusError),
        (422, UnprocessableEntityError),
        (429, RateLimitError),
        (500, InternalServerError),
        (502, InternalServerError),
        (503, ServiceUnavailableError),
    ],
)
def test_each_status_raises_its_own_error(
    make_client: Callable[..., Any], status: int, error: type[APIStatusError]
) -> None:
    client, _ = make_client(respond(status, {"title": "Refused"}), max_retries=0)
    with pytest.raises(APIStatusError) as caught:
        client.customers.get("acme")
    assert type(caught.value) is error
    assert caught.value.status_code == status


def test_the_problem_document_is_kept_whole(make_client: Callable[..., Any]) -> None:
    problem = {
        "type": "about:blank",
        "title": "Not Found",
        "status": 404,
        "detail": "license growth does not exist",
        "instance": "/api/licenses/growth",
        "code": "License.NotFound",
        "errorId": "01J9ZQK3",
        "errors": [{"location": "path.licenseSlug", "message": "unknown", "value": "growth"}],
    }
    client, _ = make_client(respond(404, problem))

    with pytest.raises(NotFoundError) as caught:
        client.licenses.get("growth")

    error = caught.value
    assert (error.code, error.title, error.detail, error.error_id) == (
        "License.NotFound",
        "Not Found",
        "license growth does not exist",
        "01J9ZQK3",
    )
    assert [detail.location for detail in error.errors] == ["path.licenseSlug"]
    assert error.request.url.path == "/api/licenses/growth"
    assert str(error) == (
        "Kaiten API error (404 Not Found) [License.NotFound]: "
        "Not Found: license growth does not exist (errorId: 01J9ZQK3)"
    )


def test_a_body_that_is_not_a_problem_is_reported_raw(make_client: Callable[..., Any]) -> None:
    client, _ = make_client(respond(502, "<html>502 Bad Gateway</html>"), max_retries=0)

    with pytest.raises(InternalServerError) as caught:
        client.customers.list()

    assert caught.value.problem is None
    assert caught.value.body == "<html>502 Bad Gateway</html>"
    assert str(caught.value) == "Kaiten API error (502 Bad Gateway): <html>502 Bad Gateway</html>"


def test_an_empty_error_body_still_names_the_status(make_client: Callable[..., Any]) -> None:
    client, _ = make_client(respond(403))
    with pytest.raises(PermissionDeniedError, match=r"^Kaiten API error \(403 Forbidden\)$"):
        client.customers.list()


def test_a_refused_usage_report_is_a_threshold_exceeded_error(
    make_client: Callable[..., Any],
) -> None:
    problem = {
        "title": "Conflict",
        "status": 409,
        "detail": "usage would exceed the maximum allowed usage",
        "code": "ReportEntitlementUsageMetric.ThresholdExceeded",
    }
    client, _ = make_client(respond(409, problem))

    with pytest.raises(ThresholdExceededError) as caught:
        client.instances.report_usage("acme-production", "seats", 5)

    assert isinstance(caught.value, ConflictError)
    assert caught.value.code == "ReportEntitlementUsageMetric.ThresholdExceeded"


def test_only_a_usage_report_reads_a_409_as_a_reached_threshold(
    make_client: Callable[..., Any],
) -> None:
    client, _ = make_client(respond(409, {"title": "Conflict", "detail": "slug is taken"}))
    with pytest.raises(ConflictError) as caught:
        client.customers.create(name="Acme", slug="acme")
    assert not isinstance(caught.value, ThresholdExceededError)


def test_another_failure_of_a_usage_report_is_not_a_threshold(
    make_client: Callable[..., Any],
) -> None:
    client, _ = make_client(respond(500, {"title": "Internal Server Error"}))
    with pytest.raises(InternalServerError) as caught:
        client.instances.report_usage("acme-production", "seats", 5)
    assert not isinstance(caught.value, ThresholdExceededError)


def test_a_success_that_is_not_json_is_a_validation_error(make_client: Callable[..., Any]) -> None:
    client, _ = make_client(respond(200, "not json"))
    with pytest.raises(APIResponseValidationError, match="not JSON"):
        client.customers.get("acme")


def test_a_success_of_the_wrong_shape_is_a_validation_error(
    make_client: Callable[..., Any],
) -> None:
    client, _ = make_client(respond(200, {"id": "an id and nothing else"}))
    with pytest.raises(APIResponseValidationError, match="Customer") as caught:
        client.customers.get("acme")
    assert caught.value.response.status_code == 200


def test_a_connection_failure_is_a_connection_error(make_client: Callable[..., Any]) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client, _ = make_client(refuse, max_retries=0)
    with pytest.raises(APIConnectionError) as caught:
        client.customers.list()
    assert isinstance(caught.value.__cause__, httpx.ConnectError)
    assert caught.value.request.url.path == "/api/customers"


def test_a_timeout_is_a_timeout_error(make_client: Callable[..., Any]) -> None:
    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    client, _ = make_client(hang, max_retries=0)
    with pytest.raises(APITimeoutError):
        client.customers.list()


@pytest.mark.parametrize(
    "error",
    [
        APIConnectionError,
        APIResponseValidationError,
        APIStatusError,
        CredentialError,
        PaginationError,
        ThresholdExceededError,
        WebhookPayloadError,
        WebhookVerificationError,
    ],
)
def test_every_sdk_error_is_a_kaiten_error(error: type[Exception]) -> None:
    assert issubclass(error, KaitenError)


def test_a_credential_error_is_also_a_value_error() -> None:
    assert issubclass(CredentialError, ValueError)
