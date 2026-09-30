# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The transport both clients share: authentication, retries, errors and pagination."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .._constants import DEFAULT_TIMEOUT, MAX_PAGE_SIZE
from .._exceptions import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    PaginationError,
    make_status_error,
)
from .._types import NOT_GIVEN, AsyncCredential, NotGiven, TimeoutTypes
from .._utils import USER_AGENT, Surface, async_resolve_token, async_sleep, check_token, retry_delay

__all__ = ["AsyncAPIClient"]

ModelT = TypeVar("ModelT", bound=BaseModel)

log = logging.getLogger("kaitencloud")

# Methods a retry cannot turn into a second effect. POST and PATCH are not among them: a usage
# report retried after a lost response is usage counted twice, and usage is what is billed.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

# Failures that happen before a request is sent, and so are safe to retry whatever its method.
NEVER_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


class AsyncAPIClient:
    """Sends a client's requests: authenticates, retries what is safe, maps errors, walks pages."""

    def __init__(
        self,
        *,
        base_url: str,
        credential: AsyncCredential,
        surface: Surface,
        max_retries: int,
        timeout: TimeoutTypes | NotGiven = NOT_GIVEN,
        default_headers: Mapping[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if max_retries < 0:
            raise ValueError(f"max_retries must be zero or more, got {max_retries}")
        self.base_url = base_url
        self.credential = credential
        self.surface = surface
        self.max_retries = max_retries
        self.timeout = timeout
        self.default_headers = dict(default_headers or {})
        self.owns_http_client = http_client is None
        self.http_client = http_client or httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT if isinstance(timeout, NotGiven) else timeout
        )

    def copy(
        self,
        *,
        timeout: TimeoutTypes | NotGiven = NOT_GIVEN,
        max_retries: int | NotGiven = NOT_GIVEN,
        default_headers: Mapping[str, str] | NotGiven = NOT_GIVEN,
    ) -> AsyncAPIClient:
        """A transport with some options changed, sharing this one's connection pool."""
        return AsyncAPIClient(
            base_url=self.base_url,
            credential=self.credential,
            surface=self.surface,
            max_retries=self.max_retries if isinstance(max_retries, NotGiven) else max_retries,
            timeout=self.timeout if isinstance(timeout, NotGiven) else timeout,
            default_headers=(
                self.default_headers if isinstance(default_headers, NotGiven) else default_headers
            ),
            http_client=self.http_client,
        )

    async def close(self) -> None:
        if self.owns_http_client:
            await self.http_client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
        idempotent: bool | None = None,
        errors: Mapping[int, type[APIStatusError]] | None = None,
    ) -> httpx.Response:
        """Send one operation and return its successful response.

        A request is retried, up to ``max_retries`` times, when it failed in a way worth
        retrying (a connection error, a 408, 429 or 5xx) *and* repeating it is safe: its method
        is idempotent, ``idempotent=True`` says so, or it never left the machine. A 401 or 403 is
        never retried -- the SDK cannot mint a better credential, and hammering a rejected one
        only burns the rate budget.
        """
        url = self.base_url + path.lstrip("/")
        retryable = method in IDEMPOTENT_METHODS if idempotent is None else idempotent
        attempt = 0

        while True:
            request = self._build(
                method, url, params=_query(params), body=body, headers=await self._headers()
            )
            try:
                response = await self.http_client.send(request)
            except httpx.TransportError as error:
                if attempt < self.max_retries and (retryable or isinstance(error, NEVER_SENT)):
                    await self._back_off(request, attempt, repr(error))
                    attempt += 1
                    continue
                if isinstance(error, httpx.TimeoutException):
                    raise APITimeoutError(request=request) from error
                raise APIConnectionError(request=request) from error

            if response.is_success:
                return response

            status = response.status_code
            if retryable and attempt < self.max_retries and (status in (408, 429) or status >= 500):
                await self._back_off(
                    request, attempt, f"HTTP {status}", response.headers.get("retry-after")
                )
                attempt += 1
                continue
            raise make_status_error(response, overrides=errors)

    async def get(
        self, path: str, model: type[ModelT], *, params: Mapping[str, Any] | None = None
    ) -> ModelT:
        return await self.send("GET", path, model, params=params)

    async def get_list(
        self, path: str, model: type[ModelT], *, params: Mapping[str, Any] | None = None
    ) -> list[ModelT]:
        """GET an unpaginated array, which the contracts type as nullable: null is empty."""
        response = await self.request("GET", path, params=params)
        data = self.decode(response)
        if data is None:
            return []
        if not isinstance(data, list):
            raise APIResponseValidationError(
                f"GET {path}: expected a JSON array, got {type(data).__name__}", response=response
            )
        return [self.validate(model, item, response) for item in data]

    async def send(
        self,
        method: str,
        path: str,
        model: type[ModelT],
        *,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
        idempotent: bool | None = None,
        errors: Mapping[int, type[APIStatusError]] | None = None,
    ) -> ModelT:
        response = await self.request(
            method, path, params=params, body=body, idempotent=idempotent, errors=errors
        )
        return self.validate(model, self.decode(response), response)

    async def send_empty(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Any = None,
        idempotent: bool | None = None,
    ) -> None:
        await self.request(method, path, params=params, body=body, idempotent=idempotent)

    async def paginate(
        self,
        path: str,
        model: type[ModelT],
        *,
        params: Mapping[str, Any] | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[ModelT]:
        """Yield every row of a cursor-paginated collection, page after page.

        ``limit`` caps how many rows are yielded, and no page asks for more rows than are still
        wanted. Without it, the walk ends only when the API says there is nothing more.
        """
        filters = dict(params or {})
        cursor: str | None = None
        yielded = 0
        items: list[Any]
        has_more: object
        next_cursor: object
        while True:
            size = MAX_PAGE_SIZE if limit is None else min(MAX_PAGE_SIZE, limit - yielded)
            response = await self.request(
                "GET", path, params={**filters, "limit": size, "cursor": cursor}
            )
            page = self.decode(response)

            if isinstance(page, list):
                # A deployment older than cursor pagination answers the whole collection.
                items, has_more, next_cursor = page, False, None
            elif isinstance(page, dict) and isinstance(page.get("items"), list):
                items, has_more, next_cursor = (
                    page["items"],
                    page.get("hasMore"),
                    page.get("nextCursor"),
                )
            else:
                raise APIResponseValidationError(
                    f"GET {path}: expected a page of items", response=response
                )

            for item in items:
                yield self.validate(model, item, response)
                yielded += 1
                if limit is not None and yielded >= limit:
                    return
            if not has_more:
                return
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor == cursor:
                raise PaginationError(
                    f"GET {path}: the API reported more rows but returned no usable next cursor"
                )
            cursor = next_cursor

    async def list_all(
        self,
        path: str,
        model: type[ModelT],
        *,
        params: Mapping[str, Any] | None = None,
        limit: int | None = None,
    ) -> list[ModelT]:
        rows: list[ModelT] = []
        async for row in self.paginate(path, model, params=params, limit=limit):
            rows.append(row)
        return rows

    @staticmethod
    def decode(response: httpx.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as error:
            raise APIResponseValidationError(
                f"{response.request.method} {response.request.url.path}: the response is not JSON",
                response=response,
            ) from error

    @staticmethod
    def validate(model: type[ModelT], data: Any, response: httpx.Response) -> ModelT:
        try:
            return model.model_validate(data)
        except ValidationError as error:
            raise APIResponseValidationError(
                f"{response.request.method} {response.request.url.path}: the response does not "
                f"match {model.__name__}: {error}",
                response=response,
            ) from error

    def _build(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None,
        body: Any,
        headers: dict[str, str],
    ) -> httpx.Request:
        if isinstance(self.timeout, NotGiven):
            # The HTTP client's own timeout applies: the default one, or the caller's.
            return self.http_client.build_request(
                method, url, params=params, json=body, headers=headers
            )
        return self.http_client.build_request(
            method, url, params=params, json=body, headers=headers, timeout=self.timeout
        )

    async def _headers(self) -> dict[str, str]:
        token = check_token(await async_resolve_token(self.credential), self.surface)
        return {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            **self.default_headers,
            "Authorization": f"Bearer {token}",
        }

    async def _back_off(
        self, request: httpx.Request, attempt: int, reason: str, retry_after: str | None = None
    ) -> None:
        delay = retry_delay(attempt, retry_after)
        log.info(
            "Retrying %s %s in %.2fs (retry %d of %d) after %s",
            request.method,
            request.url.path,
            delay,
            attempt + 1,
            self.max_retries,
            reason,
        )
        await async_sleep(delay)


def _query(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not params:
        return None
    query: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        query[key] = ("true" if value else "false") if isinstance(value, bool) else value
    return query
