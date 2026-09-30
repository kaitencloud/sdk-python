# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Verify and parse the webhooks Kaiten delivers.

Kaiten delivers webhooks through Svix. Every delivery carries ``svix-id``, ``svix-timestamp``
and ``svix-signature`` headers, signed with your endpoint's ``whsec_...`` secret. Verify the
*raw* request body -- before any JSON parsing, which would change the bytes signed -- then act
on the typed event::

    from kaitencloud.webhooks import (
        InstanceEntitlementCapExceededEvent,
        WebhookVerificationError,
        verify_webhook,
    )

    @app.post("/webhooks/kaiten")
    async def kaiten_webhook(request: Request) -> Response:
        try:
            event = verify_webhook(await request.body(), request.headers, secret=SIGNING_SECRET)
        except WebhookVerificationError:
            return Response(status_code=400)

        if isinstance(event, InstanceEntitlementCapExceededEvent):
            notify_sales(event.data.entitlement_slug, event.data.overage)
        return Response(status_code=204)

Every event published by the API has a model here, named after it. An event newer than the
SDK you run parses as :class:`UnknownWebhookEvent` rather than failing.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from collections.abc import Mapping
from datetime import timedelta
from typing import Any, Final

from pydantic import ValidationError

from ._exceptions import WebhookPayloadError, WebhookVerificationError
from ._models import KaitenModel
from .types import _webhooks
from .types._webhooks import *  # noqa: F403 -- every event model is part of this module's API
from .types._webhooks import WEBHOOK_EVENTS, WebhookEvent

__all__ = [
    "DEFAULT_TOLERANCE",
    "UnknownWebhookEvent",
    "Webhook",
    "WebhookPayloadError",
    "WebhookVerificationError",
    "parse_event",
    "verify_webhook",
]
__all__ += _webhooks.__all__

DEFAULT_TOLERANCE: Final = timedelta(minutes=5)
"""How far a delivery's timestamp may be from now, in either direction, to be accepted."""

_SECRET_PREFIX = "whsec_"


class UnknownWebhookEvent(KaitenModel):
    """An event this version of the SDK has no model for, typically one published after it."""

    name: str
    type: str
    data: Any = None


class Webhook:
    """A verifier for one webhook endpoint's signing secret.

    Build it once and reuse it: the secret is decoded, and validated, on construction.

    Args:
        secret: The endpoint's signing secret, ``whsec_...``.
        tolerance: How far a delivery's timestamp may be from now, either way, before it is
            refused as a replay. Defaults to five minutes.
    """

    def __init__(self, secret: str, *, tolerance: timedelta | float = DEFAULT_TOLERANCE) -> None:
        self._key = _decode_secret(secret)
        self._tolerance = (
            tolerance.total_seconds() if isinstance(tolerance, timedelta) else float(tolerance)
        )

    def verify(
        self, payload: bytes | str, headers: Mapping[str, str]
    ) -> WebhookEvent | UnknownWebhookEvent:
        """Verify a delivery and return its event.

        Args:
            payload: The raw request body, exactly as received.
            headers: The request headers. Any mapping works; names are matched
                case-insensitively.

        Raises:
            WebhookVerificationError: A header is missing, the timestamp is outside the
                tolerance, or no signature matches. Answer 400 and do not act on it.
            WebhookPayloadError: The delivery is authentic but does not match the contract of
                the event it names.
        """
        body = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
        lowered = {name.lower(): value for name, value in headers.items()}
        message_id = _header(lowered, "id")
        timestamp = _header(lowered, "timestamp")
        signatures = _header(lowered, "signature")

        self._check_timestamp(timestamp)
        signed = f"{message_id}.{timestamp}.".encode() + body
        expected = base64.b64encode(hmac.new(self._key, signed, hashlib.sha256).digest()).decode()
        for candidate in signatures.split():
            version, _, signature = candidate.partition(",")
            if version == "v1" and hmac.compare_digest(signature, expected):
                return parse_event(body)
        raise WebhookVerificationError("No signature matches the payload.")

    def _check_timestamp(self, timestamp: str) -> None:
        try:
            sent = int(timestamp)
        except ValueError:
            raise WebhookVerificationError(f"Invalid timestamp header: {timestamp!r}") from None
        now = time.time()
        if sent < now - self._tolerance:
            raise WebhookVerificationError("The delivery's timestamp is too old.")
        if sent > now + self._tolerance:
            raise WebhookVerificationError("The delivery's timestamp is in the future.")


def verify_webhook(
    payload: bytes | str,
    headers: Mapping[str, str],
    *,
    secret: str,
    tolerance: timedelta | float = DEFAULT_TOLERANCE,
) -> WebhookEvent | UnknownWebhookEvent:
    """Verify a delivery with ``secret`` and return its event. See :meth:`Webhook.verify`."""
    return Webhook(secret, tolerance=tolerance).verify(payload, headers)


def parse_event(payload: bytes | str | Mapping[str, Any]) -> WebhookEvent | UnknownWebhookEvent:
    """Parse an event without verifying it -- for tests, or a payload verified upstream."""
    if isinstance(payload, Mapping):
        data: Any = dict(payload)
    else:
        try:
            data = json.loads(payload)
        except ValueError as error:
            raise WebhookPayloadError("The webhook payload is not JSON.") from error
    if not isinstance(data, dict):
        raise WebhookPayloadError("The webhook payload is not a JSON object.")

    model = WEBHOOK_EVENTS.get(str(data.get("type")))
    try:
        if model is None:
            return UnknownWebhookEvent.model_validate(data)
        event: WebhookEvent = model.model_validate(data)  # type: ignore[assignment]
    except ValidationError as error:
        raise WebhookPayloadError(
            f"The webhook payload does not match the {data.get('type')!r} event: {error}"
        ) from error
    return event


def _decode_secret(secret: str) -> bytes:
    value = secret.strip()
    if value.startswith(_SECRET_PREFIX):
        value = value[len(_SECRET_PREFIX) :]
    try:
        key = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        key = b""
    if not key:
        raise ValueError("The webhook signing secret is not a valid whsec_... secret.")
    return key


def _header(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(f"svix-{name}") or headers.get(f"webhook-{name}")
    if not value:
        raise WebhookVerificationError(f"The svix-{name} header is missing.")
    return value
