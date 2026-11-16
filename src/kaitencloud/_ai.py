# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The provider-agnostic pieces of AI usage metering, shared by the sync and async code.

Nothing here talks to the network: transaction ids, the wire shape of a usage, the
normalisers that read a provider's usage object, the default estimator and the rule that
tells a provider error from a call that never left the machine.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Literal, get_args

import httpx

from .types import AiRequestStatus, AiRequestType, AiUsageParam

__all__ = [
    "AI_WARNINGS",
    "DEFAULT_OUTPUT_TOKENS",
    "AiRequest",
    "AiWarning",
    "Estimator",
    "ProviderVendorCostOf",
    "UsageOf",
    "VendorCost",
    "VendorCostOf",
    "add_usage",
    "ai_usage_body",
    "check_transaction_id",
    "default_estimator",
    "exact_decimal",
    "from_anthropic",
    "from_openai",
    "new_idempotency_key",
    "new_transaction_id",
    "request_status_of",
    "ttl_from_timeout",
    "vendor_cost_string",
]

AI_MAX_RETRIES: Final = 3
"""How many times a reservation or a commit is retried, under the same key."""

AI_RETRY_STATUSES: Final = frozenset({500, 502, 503, 504})
"""The statuses a reservation or a commit is retried on. Never a 4xx."""

MAX_TTL_SECONDS: Final = 3600
"""The longest reservation the API grants by default (``KAITEN_AI_RESERVATION_MAX_TTL``)."""

DEFAULT_OUTPUT_TOKENS: Final[Mapping[str, int]] = {"COMPLETION": 1024, "EMBEDDING": 0}
"""The output a request that sets no ceiling is expected to produce, per request type."""

AiWarning = Literal[
    "RESERVATION_EXPIRED",
    "MODEL_DEPRECATED",
    "ESTIMATE_INCOMPLETE",
    "CONVERSION_INPUT_MISSING",
    "OVERDRAWN",
    "MODEL_NOT_AUTHORIZED",
    "UNKNOWN_MODEL",
    "NO_RESERVATION",
    "COUNTER_PRECISION_DEGRADED",
    "PRICING_SNAPSHOT_UNREADABLE",
]
"""The warnings an AI answer or an inference row may carry, as this release knows them.

An open set: ``warnings`` is typed ``list[str]``, and a warning a later Kaiten adds parses like
any other string. Compare against these names; never treat an unknown one as an error.

- ``NO_RESERVATION``: a release (``NOT_SENT``) of a transaction that never reserved. Nothing
  was held, nothing is charged, and the transaction id is closed for good: a reserve or a
  commit sent under it afterwards is refused with ``TransactionIdReusedError``.
- ``COUNTER_PRECISION_DEGRADED``: the commit was recorded, but the pool's counter can no longer
  hold the charge exactly; the inference row keeps the exact credits.
- ``PRICING_SNAPSHOT_UNREADABLE``: an inference row whose pricing snapshot could not be read.
"""

AI_WARNINGS: Final[frozenset[str]] = frozenset(get_args(AiWarning))
"""Every warning name in :data:`AiWarning`."""

VendorCost = Decimal | str | int
"""What a call cost at its vendor, in USD: a ``Decimal``, a decimal string or a whole number.

Never a ``float``: a binary float cannot say ``0.1``, and the commit must carry the exact
figure. Up to 12 integer digits and 12 decimal places.
"""

VendorCostOf = Callable[[Any], "VendorCost | None"]
"""Reads a call's vendor cost out of what the call returned; ``None`` when unknown."""

ProviderVendorCostOf = Callable[["AiRequest", "AiUsageParam | None", Any], "VendorCost | None"]
"""A provider call's vendor cost, from the request, its usage and its response.

The response is ``None`` for a stream. The SDK knows no price: this is the caller's own price
table, or a cost the provider's response reports. ``None`` commits without a vendor cost.
"""

_TRANSACTION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

_USAGE_KEYS: Final = {
    "input_tokens": "inputTokens",
    "cache_read_input_tokens": "cacheReadInputTokens",
    "cache_write_input_tokens": "cacheWriteInputTokens",
    "output_tokens": "outputTokens",
    "duration_ms": "durationMs",
}


def new_transaction_id() -> str:
    """A fresh UUIDv7: time-ordered, so a pool's operations sort by when they started."""
    milliseconds = time.time_ns() // 1_000_000
    value = (milliseconds & (2**48 - 1)) << 80 | int.from_bytes(os.urandom(10), "big")
    value = (value & ~(0xF << 76)) | (0x7 << 76)  # version 7
    value = (value & ~(0x3 << 62)) | (0x2 << 62)  # RFC 4122 variant
    return str(uuid.UUID(int=value))


def check_transaction_id(value: str) -> str:
    """``value``, when the API accepts it as a transaction id; ``ValueError`` otherwise."""
    if not isinstance(value, str) or not _TRANSACTION_ID.fullmatch(value):
        raise ValueError(
            "a transaction id is 1 to 128 characters among letters, digits and . _ : -, "
            f"got {value!r}"
        )
    return value


def new_idempotency_key() -> str:
    """A fresh idempotency key for a refund: a UUIDv7, which the API accepts as a key."""
    return new_transaction_id()


def vendor_cost_string(value: VendorCost) -> str:
    """``value`` as the commit's ``vendorCost`` sends it; ``ValueError`` when it cannot be sent.

    A string is checked and sent exactly as given -- ``"0.010"`` stays ``"0.010"`` -- and a
    ``Decimal`` keeps its own digits, trailing zeros included (``Decimal("0.010")`` sends
    ``"0.010"``). The spelling matters: it is part of the commit's identity, so a commit sent
    again must carry the same string, or the API refuses it as another body
    (``TransactionIdReusedError``). Converted once per commit; the SDK's retries resend it.
    """
    return exact_decimal(value, name="vendor_cost", decimals=12)


def exact_decimal(value: VendorCost, *, name: str, decimals: int) -> str:
    """``value`` as an exact decimal string of up to 12 integer digits and ``decimals`` places.

    Never rounded and never reformatted: a string is checked and kept as written.
    """
    if isinstance(value, bool) or not isinstance(value, (Decimal, str, int)):
        raise ValueError(f"{name} must be a Decimal, a decimal string or an int, got {value!r}")
    if isinstance(value, str):
        text = value
    else:
        number = Decimal(value)
        if not number.is_finite():
            raise ValueError(f"{name} must be a finite amount, got {value!r}")
        text = format(number, "f")
    if re.fullmatch(rf"[0-9]{{1,12}}(\.[0-9]{{1,{decimals}}})?", text) is None:
        raise ValueError(
            f"{name} must be zero or more, with 1 to 12 integer digits and at most {decimals} "
            f"decimal places, got {value!r}"
        )
    return text


def ai_usage_body(usage: AiUsageParam) -> dict[str, Any]:
    """``usage`` as the API spells it, every count checked."""
    body: dict[str, Any] = {}
    for key, wire in _USAGE_KEYS.items():
        if key in usage:
            count = usage[key]  # type: ignore[literal-required]
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError(
                    f"usage {key} must be a whole number of zero or more, got {count!r}"
                )
            body[wire] = count
    if "units" in usage:
        body["units"] = _decimal_string(usage["units"])
    if "unit_type" in usage:
        body["unitType"] = usage["unit_type"]
    unknown = set(usage) - set(_USAGE_KEYS) - {"units", "unit_type"}
    if unknown:
        raise ValueError(f"unknown usage fields: {', '.join(sorted(unknown))}")
    return body


def _decimal_string(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise ValueError(f"usage units must be an int, a str or a Decimal, got {value!r}")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"usage units must be a decimal number, got {value!r}") from error
    if not number.is_finite() or number < 0:
        raise ValueError(f"usage units must be zero or more, got {value!r}")
    text = format(number, "f")
    if re.fullmatch(r"[0-9]{1,12}(\.[0-9]{1,6})?", text) is None:
        raise ValueError(
            "usage units must have 1 to 12 integer digits and at most 6 decimal places"
        )
    return text


def add_usage(*usages: AiUsageParam | None) -> AiUsageParam:
    """The sum of ``usages``, field by field: a stream's usage is the sum of its parts."""
    total: dict[str, Any] = {}
    for usage in usages:
        for key, value in dict(usage or {}).items():
            if key == "unit_type":
                total[key] = value
            elif key == "units":
                total[key] = str(Decimal(str(total.get(key, 0))) + Decimal(str(value)))
            else:
                total[key] = total.get(key, 0) + value
    return total  # type: ignore[return-value]


# -- normalisers ---------------------------------------------------------------------------


def _get(source: Any, name: str) -> Any:
    if source is None:
        return None
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _count(source: Any, name: str) -> int:
    value = _get(source, name)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def from_openai(usage: Any) -> AiUsageParam:
    """An OpenAI usage object -- Chat Completions, Responses, Embeddings, Images or Audio --
    as the disjoint fields of an :class:`~kaitencloud.types.AiUsageParam`.

    OpenAI counts cached input inside the input: ``prompt_tokens`` (or ``input_tokens``)
    includes ``cached_tokens`` and ``cache_write_tokens``, so both are taken out of
    ``input_tokens``. Reasoning tokens are already inside the output count. A transcription
    billed by duration reports ``seconds``, kept as ``duration_ms``. Accepts the provider's
    pydantic models and plain dictionaries alike; ``None`` gives an empty usage.
    """
    if usage is None:
        return {}
    if _get(usage, "type") == "duration":
        seconds = _get(usage, "seconds") or 0
        return {"duration_ms": max(round(float(seconds) * 1000), 0)}

    if _get(usage, "prompt_tokens") is not None:
        total_input = _count(usage, "prompt_tokens")
        details = _get(usage, "prompt_tokens_details")
        output = _count(usage, "completion_tokens")
    else:
        total_input = _count(usage, "input_tokens")
        details = _get(usage, "input_tokens_details") or _get(usage, "input_token_details")
        output = _count(usage, "output_tokens")
    cached = _count(details, "cached_tokens")
    written = _count(details, "cache_write_tokens")

    normalised: AiUsageParam = {"input_tokens": max(total_input - cached - written, 0)}
    if cached:
        normalised["cache_read_input_tokens"] = cached
    if written:
        normalised["cache_write_input_tokens"] = written
    normalised["output_tokens"] = output
    return normalised


def from_anthropic(usage: Any) -> AiUsageParam:
    """An Anthropic usage object as the disjoint fields of an
    :class:`~kaitencloud.types.AiUsageParam`.

    Anthropic already counts cache reads and writes apart from ``input_tokens``, so the fields
    map one to one. Accepts the provider's models and plain dictionaries alike -- the Claude
    Agent SDK hands usage over as a dictionary -- and ``None`` gives an empty usage.
    """
    if usage is None:
        return {}
    normalised: AiUsageParam = {"input_tokens": _count(usage, "input_tokens")}
    if read := _count(usage, "cache_read_input_tokens"):
        normalised["cache_read_input_tokens"] = read
    if written := _count(usage, "cache_creation_input_tokens"):
        normalised["cache_write_input_tokens"] = written
    normalised["output_tokens"] = _count(usage, "output_tokens")
    return normalised


# -- estimation ----------------------------------------------------------------------------


@dataclass(frozen=True)
class AiRequest:
    """A call about to be made, as an estimator sees it."""

    provider: str
    """``"openai"``, ``"anthropic"``, or the agent SDK running the turn."""

    operation: str
    """The method called, e.g. ``"chat.completions.create"``."""

    model: str
    """The model asked for."""

    request_type: AiRequestType
    """What the call produces."""

    params: Mapping[str, Any] = field(default_factory=dict)
    """The call's keyword arguments, as given."""


Estimator = Callable[[AiRequest], "AiUsageParam | None"]
"""Turns a request into the usage to reserve. ``None`` reserves without an estimate."""

UsageOf = Callable[[Any], "AiUsageParam | None"]
"""Reads the usage out of what a provider call returned."""

# The arguments that carry a request's prompt, per operation. Only their size is used.
_PROMPT_PARAMS: Final[Mapping[str, tuple[str, ...]]] = {
    "chat.completions.create": ("messages", "tools"),
    "responses.create": ("instructions", "input", "tools"),
    "embeddings.create": ("input",),
    "images.generate": ("prompt",),
    "audio.speech.create": ("input",),
    "messages.create": ("system", "messages", "tools"),
    "messages.stream": ("system", "messages", "tools"),
}
_OUTPUT_CEILINGS: Final = ("max_completion_tokens", "max_output_tokens", "max_tokens")


def default_estimator(request: AiRequest) -> AiUsageParam:
    """A heuristic of the usage ``request`` will report: never a dependency, never exact.

    Input is the serialized prompt's size in bytes over four. Output is the ceiling the
    request sets (``max_completion_tokens``, ``max_output_tokens`` or ``max_tokens``), else
    1024 for a completion and 0 for an embedding. An image generation reserves its ``n``
    images. Over-estimating only inflates a reservation the commit settles; plug a real
    tokenizer in through ``estimator=`` when that matters.
    """
    params = request.params
    if request.request_type == "IMAGE_GENERATION":
        count = params.get("n")
        return {"units": count if isinstance(count, int) and count > 0 else 1, "unit_type": "image"}

    estimate: AiUsageParam = {}
    prompt = [params[name] for name in _PROMPT_PARAMS.get(request.operation, ()) if name in params]
    if prompt:
        size = len(json.dumps(prompt, default=str, ensure_ascii=False).encode("utf-8"))
        estimate["input_tokens"] = math.ceil(size / 4)
    ceiling = next(
        (params[name] for name in _OUTPUT_CEILINGS if isinstance(params.get(name), int)), None
    )
    if ceiling is not None:
        estimate["output_tokens"] = max(ceiling, 0)
    elif request.request_type in DEFAULT_OUTPUT_TOKENS:
        estimate["output_tokens"] = DEFAULT_OUTPUT_TOKENS[request.request_type]
    return estimate


def ttl_from_timeout(timeout: Any) -> int | None:
    """A reservation lifetime matching a provider timeout, or ``None`` for the server's default.

    A number is seconds; an ``httpx``-style timeout object counts by its longest phase.
    """
    if isinstance(timeout, bool):
        return None
    if isinstance(timeout, (int, float)):
        seconds: float | None = float(timeout)
    else:
        phases = [getattr(timeout, name, None) for name in ("connect", "read", "write", "pool")]
        numbers = [
            float(p) for p in phases if isinstance(p, (int, float)) and not isinstance(p, bool)
        ]
        seconds = max(numbers) if numbers else None
    if seconds is None or not math.isfinite(seconds) or seconds <= 0:
        return None
    return min(math.ceil(seconds), MAX_TTL_SECONDS)


def request_status_of(error: BaseException) -> AiRequestStatus:
    """How a provider call that raised ``error`` ended, as a commit reports it.

    An HTTP answer is the provider's (5xx, 408, 429) or the caller's (any other 4xx).
    Only explicit connection establishment or pool acquisition failures prove the call was
    not sent. A call the caller abandoned -- a cancelled task, ``KeyboardInterrupt``, any
    ``BaseException`` that is not an ``Exception`` -- may have been sent, and is the caller's:
    ``CUSTOMER_ERROR``. Other failures may happen after sending, so they are conservatively
    reported as ``PROVIDER_ERROR``, never released as ``NOT_SENT``.
    """
    if not isinstance(error, Exception):
        return "CUSTOMER_ERROR"
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        if status >= 500 or status in (408, 429):
            return "PROVIDER_ERROR"
        if status >= 400:
            return "CUSTOMER_ERROR"
    if isinstance(
        error,
        (ConnectionRefusedError, httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout),
    ):
        return "NOT_SENT"
    return "PROVIDER_ERROR"
