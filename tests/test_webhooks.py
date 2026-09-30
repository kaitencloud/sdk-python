# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Webhook deliveries: verified like Svix signs them, parsed into their typed events."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta
from typing import Any

import pytest
from contract import document, sample

from kaitencloud import WebhookPayloadError, WebhookVerificationError
from kaitencloud.webhooks import (
    WEBHOOK_EVENTS,
    InstanceEntitlementCapExceededEvent,
    UnknownWebhookEvent,
    Webhook,
    parse_event,
    verify_webhook,
)

SECRET = "whsec_" + base64.b64encode(b"kaiten-test-signing-key-32-bytes").decode()
EVENT = {
    "name": "INSTANCE_ENTITLEMENT_CAP_EXCEEDED",
    "type": "com.kaiten.instance.entitlement.v1.cap_exceeded",
    "data": {"entitlement_slug": "seats", "threshold": 100, "value": 105, "overage": 5},
    "headers": {},
}
PAYLOAD = json.dumps(EVENT).encode()


def sign(
    payload: bytes, *, secret: str = SECRET, message_id: str = "msg_2abc", at: float | None = None
) -> dict[str, str]:
    """The headers Svix sends with a delivery of ``payload``."""
    timestamp = str(int(time.time() if at is None else at))
    key = base64.b64decode(secret.removeprefix("whsec_"))
    digest = hmac.new(key, f"{message_id}.{timestamp}.".encode() + payload, hashlib.sha256)
    return {
        "svix-id": message_id,
        "svix-timestamp": timestamp,
        "svix-signature": "v1," + base64.b64encode(digest.digest()).decode(),
    }


def test_a_signed_delivery_verifies_into_its_typed_event() -> None:
    event = verify_webhook(PAYLOAD, sign(PAYLOAD), secret=SECRET)
    assert isinstance(event, InstanceEntitlementCapExceededEvent)
    assert (event.data.entitlement_slug, event.data.overage) == ("seats", 5)


def test_svix_reference_signature_verifies(monkeypatch: pytest.MonkeyPatch) -> None:
    # The worked example of Svix's documentation, cross-checked against the svix library.
    monkeypatch.setattr(time, "time", lambda: 1614265330.0)
    headers = {
        "svix-id": "msg_p5jXN8AQM9LWM0D4loKWxJek",
        "svix-timestamp": "1614265330",
        "svix-signature": "v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=",
    }
    # The signature matches, so verification reaches parsing -- and this payload is no event.
    with pytest.raises(WebhookPayloadError):
        verify_webhook(
            '{"test": 2432232314}', headers, secret="whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
        )


def test_a_tampered_payload_is_refused() -> None:
    headers = sign(PAYLOAD)
    with pytest.raises(WebhookVerificationError, match="signature"):
        verify_webhook(PAYLOAD.replace(b"105", b"999"), headers, secret=SECRET)


def test_a_delivery_signed_with_another_secret_is_refused() -> None:
    other = "whsec_" + base64.b64encode(b"another-endpoint-secret").decode()
    with pytest.raises(WebhookVerificationError):
        verify_webhook(PAYLOAD, sign(PAYLOAD, secret=other), secret=SECRET)


@pytest.mark.parametrize("offset", [-301, 301], ids=["too old", "in the future"])
def test_a_delivery_outside_the_tolerance_is_refused_either_way(offset: int) -> None:
    headers = sign(PAYLOAD, at=time.time() + offset)
    with pytest.raises(WebhookVerificationError, match="timestamp"):
        verify_webhook(PAYLOAD, headers, secret=SECRET)


def test_the_tolerance_can_be_widened() -> None:
    headers = sign(PAYLOAD, at=time.time() - 600)
    event = verify_webhook(PAYLOAD, headers, secret=SECRET, tolerance=timedelta(minutes=15))
    assert isinstance(event, InstanceEntitlementCapExceededEvent)


def test_a_timestamp_that_is_not_a_number_is_refused() -> None:
    headers = {**sign(PAYLOAD), "svix-timestamp": "yesterday"}
    with pytest.raises(WebhookVerificationError, match="timestamp"):
        verify_webhook(PAYLOAD, headers, secret=SECRET)


def test_any_matching_signature_verifies_during_a_secret_rotation() -> None:
    headers = sign(PAYLOAD)
    headers["svix-signature"] = "v1,c3RhbGU= " + headers["svix-signature"]
    assert isinstance(
        verify_webhook(PAYLOAD, headers, secret=SECRET), InstanceEntitlementCapExceededEvent
    )


def test_only_v1_signatures_count() -> None:
    headers = sign(PAYLOAD)
    headers["svix-signature"] = headers["svix-signature"].replace("v1,", "v2,")
    with pytest.raises(WebhookVerificationError):
        verify_webhook(PAYLOAD, headers, secret=SECRET)


@pytest.mark.parametrize("missing", ["svix-id", "svix-timestamp", "svix-signature"])
def test_a_missing_header_is_refused(missing: str) -> None:
    headers = sign(PAYLOAD)
    del headers[missing]
    with pytest.raises(WebhookVerificationError, match=missing):
        verify_webhook(PAYLOAD, headers, secret=SECRET)


def test_unbranded_webhook_headers_are_accepted() -> None:
    headers = {name.replace("svix-", "webhook-"): value for name, value in sign(PAYLOAD).items()}
    assert isinstance(
        verify_webhook(PAYLOAD, headers, secret=SECRET), InstanceEntitlementCapExceededEvent
    )


def test_header_names_are_matched_case_insensitively() -> None:
    headers = {name.title(): value for name, value in sign(PAYLOAD).items()}
    assert isinstance(
        verify_webhook(PAYLOAD, headers, secret=SECRET), InstanceEntitlementCapExceededEvent
    )


def test_a_text_payload_verifies_like_bytes() -> None:
    event = Webhook(SECRET).verify(PAYLOAD.decode(), sign(PAYLOAD))
    assert isinstance(event, InstanceEntitlementCapExceededEvent)


@pytest.mark.parametrize("secret", ["", "whsec_", "whsec_not base64!"])
def test_a_malformed_secret_is_refused_upfront(secret: str) -> None:
    with pytest.raises(ValueError, match="whsec_"):
        Webhook(secret)


def test_an_event_newer_than_the_sdk_parses_as_unknown() -> None:
    payload = json.dumps(
        {"name": "INVOICE_PAID", "type": "com.kaiten.invoice.v1.paid", "data": {"amount": 1}}
    ).encode()
    event = verify_webhook(payload, sign(payload), secret=SECRET)
    assert isinstance(event, UnknownWebhookEvent)
    assert (event.type, event.data) == ("com.kaiten.invoice.v1.paid", {"amount": 1})


def test_an_authentic_payload_that_breaks_its_contract_is_a_payload_error() -> None:
    payload = json.dumps({**EVENT, "data": {"entitlement_slug": "seats"}}).encode()
    with pytest.raises(WebhookPayloadError, match="cap_exceeded"):
        verify_webhook(payload, sign(payload), secret=SECRET)


@pytest.mark.parametrize("payload", [b"not json", b"[1, 2]"], ids=["not json", "not an object"])
def test_a_payload_that_is_not_an_event_object_is_a_payload_error(payload: bytes) -> None:
    with pytest.raises(WebhookPayloadError):
        parse_event(payload)


@pytest.mark.parametrize("event_type", sorted(document("core")["webhooks"]))
def test_every_published_event_parses_a_payload_shaped_like_its_contract(event_type: str) -> None:
    schema = document("core")["webhooks"][event_type]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]

    full: dict[str, Any] = sample(schema, "core")
    event = parse_event(full)
    assert type(event) is WEBHOOK_EVENTS[event_type]
    assert event.to_dict() == full

    assert type(parse_event(sample(schema, "core", full=False))) is WEBHOOK_EVENTS[event_type]
