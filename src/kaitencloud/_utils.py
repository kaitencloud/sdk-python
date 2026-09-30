# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Helpers shared by the sync and async implementations."""

from __future__ import annotations

import asyncio
import email.utils
import inspect
import platform
import random
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from urllib.parse import quote

import httpx

from ._constants import INITIAL_RETRY_DELAY, MAX_RETRY_AFTER, MAX_RETRY_DELAY
from ._exceptions import CredentialError
from ._models import KaitenModel
from ._types import AsyncCredential, Credential, EntitlementValueInput
from ._version import __version__
from .types import IntegrationParam

USER_AGENT = (
    f"kaitencloud-python/{__version__} "
    f"(python {platform.python_version()}; httpx {httpx.__version__})"
)

Surface = Literal["core", "platform"]


def normalize_base_url(url: str) -> str:
    """Return ``url`` as the absolute ``.../api/`` prefix every operation path joins onto.

    Both Kaiten APIs are served under ``/api`` and their contracts publish bare paths below
    it, so ``https://kaiten.example.com`` and ``https://kaiten.example.com/api`` must mean the same
    thing: without the suffix, every call would answer 404.
    """
    candidate = url.strip()
    try:
        parsed = httpx.URL(candidate)
    except httpx.InvalidURL as error:
        raise ValueError(f"base_url is not a valid URL: {url!r}") from error
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise ValueError(f"base_url must be an absolute http(s) URL, got {url!r}")
    path = parsed.path.rstrip("/")
    if not path.endswith("/api"):
        path = f"{path}/api"
    return f"{parsed.scheme}://{parsed.netloc.decode('ascii')}{path}/"


def api_path(*segments: str) -> str:
    """Join path segments into an operation path, escaping each one.

    Slugs and names come from callers, not from the API, so they are escaped rather than
    trusted -- and an empty one is refused, because it would silently address the collection
    instead of a member of it.
    """
    escaped = []
    for segment in segments:
        if not isinstance(segment, str) or not segment.strip():
            raise ValueError(f"path segments must be non-empty strings, got {segment!r}")
        escaped.append(quote(segment, safe=""))
    return "/" + "/".join(escaped)


def compact(fields: Mapping[str, Any]) -> dict[str, Any]:
    """``fields`` without the entries whose value is ``None``.

    An optional field left unset must be absent from a request body, not null: every Kaiten
    request body is ``additionalProperties: false`` and several fields refuse an explicit null.
    """
    return {key: value for key, value in fields.items() if value is not None}


def format_datetime(value: datetime | str) -> str:
    """``value`` as an RFC 3339 timestamp. Strings pass through unchanged."""
    if isinstance(value, str):
        return value
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{value!r} has no timezone: pass an aware datetime, "
            "e.g. datetime(2027, 1, 1, tzinfo=timezone.utc)"
        )
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def optional_datetime(value: datetime | str | None) -> str | None:
    return None if value is None else format_datetime(value)


def format_duration(value: timedelta | str) -> str:
    """``value`` as the Go duration the Platform API parses, e.g. ``"900s"``."""
    if isinstance(value, str):
        return value
    seconds = value.total_seconds()
    if seconds <= 0:
        raise ValueError(f"a duration must be positive, got {value!r}")
    return f"{int(seconds)}s" if seconds.is_integer() else f"{seconds}s"


def entitlement_value(value: EntitlementValueInput | KaitenModel) -> dict[str, Any]:
    """Wrap a plain value in the typed envelope the API expects for an entitlement value."""
    if isinstance(value, KaitenModel):
        return {key: item for key, item in value.to_dict().items() if key != "event_count"}
    if isinstance(value, bool):
        return {"type": "boolean", "value": value}
    if isinstance(value, (int, float)):
        return {"type": "number", "value": value}
    if isinstance(value, Mapping):
        return {"type": "object", "value": dict(value)}
    raise TypeError(
        "an entitlement value is a bool (BOOLEAN), a number (NUMBER) or a mapping (CONFIG), "
        f"got {type(value).__name__}"
    )


def integration_body(
    *,
    external_id: str,
    metadata: Mapping[str, Any] | None,
    web_url: str | None,
    last_error: str | None,
) -> dict[str, Any]:
    """The body of an integration: a customer's or an instance's link to an external record."""
    return compact(
        {
            "external_id": external_id,
            "metadata": dict(metadata) if metadata is not None else None,
            "web_url": web_url,
            "last_error": last_error,
        }
    )


def integrations_body(
    integrations: Mapping[str, IntegrationParam] | None,
) -> dict[str, dict[str, Any]] | None:
    if integrations is None:
        return None
    return {name: dict(integration) for name, integration in integrations.items()}


def validate_uuid(value: str, name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise ValueError(f"{name} must be a UUID, got {value!r}") from None


def check_token(token: object, surface: Surface) -> str:
    """Return ``token`` when the API ``surface`` accepts its credential class; raise otherwise.

    Each Kaiten listener refuses the other's credential with a deliberately uninformative
    error. Catching the mix-up here, before a request leaves, is the only place a useful
    message can come from.
    """
    if not isinstance(token, str) or not token.strip():
        raise CredentialError("The token is empty.")
    token = token.strip()
    if token.startswith("whsec_"):
        raise CredentialError(
            "whsec_... is a webhook signing secret, not an API credential: "
            "pass it to kaitencloud.webhooks.verify_webhook() instead."
        )
    if surface == "core" and token.startswith("ksm_"):
        raise CredentialError(
            "A platform credential (ksm_...) cannot call the Core API, which refuses it. "
            "Use KaitenPlatformClient, or mint an organization token with it."
        )
    if surface == "platform" and not token.startswith("ksm_"):
        raise CredentialError(
            "The Platform API only accepts platform credentials (ksm_...). Organization "
            "tokens (ksh_...) and identity-provider JWTs belong to KaitenClient."
        )
    return token


async def async_resolve_token(credential: AsyncCredential) -> object:
    if not callable(credential):
        return credential
    value = credential()
    if inspect.isawaitable(value):
        return await value
    return value


def resolve_token(credential: Credential) -> object:
    return credential() if callable(credential) else credential


def retry_delay(attempt: int, retry_after: str | None = None) -> float:
    """Seconds to wait before retrying, after ``attempt`` retries already happened.

    A ``Retry-After`` header wins when the server sent one; otherwise the delay backs off
    exponentially with jitter, so clients that failed together do not retry together.
    """
    if retry_after:
        seconds = _parse_retry_after(retry_after)
        if seconds is not None:
            return min(max(seconds, 0.0), MAX_RETRY_AFTER)
    delay = INITIAL_RETRY_DELAY * 2**attempt * (1 + random.random())
    return float(min(delay, MAX_RETRY_DELAY))


def _parse_retry_after(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        pass
    try:
        moment = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment - datetime.now(timezone.utc)).total_seconds()


async def async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


def sleep(seconds: float) -> None:
    time.sleep(seconds)
