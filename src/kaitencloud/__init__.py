# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The official Python SDK for Kaiten.

::

    from kaitencloud import KaitenClient

    client = KaitenClient(token="ksh_...")
    for instance in client.instances.list():
        print(instance.slug, instance.status)
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from . import targeting, types, usage
from ._async.client import AsyncKaitenClient, AsyncKaitenPlatformClient
from ._constants import DEFAULT_MAX_RETRIES, DEFAULT_TIMEOUT
from ._exceptions import (
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
from ._models import KaitenModel
from ._sync.client import KaitenClient, KaitenPlatformClient
from ._types import NOT_GIVEN, NotGiven
from ._version import __version__
from .usage import UNLIMITED

if TYPE_CHECKING:
    from . import webhooks

__all__ = [
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_TIMEOUT",
    "NOT_GIVEN",
    "UNLIMITED",
    "APIConnectionError",
    "APIResponseValidationError",
    "APIStatusError",
    "APITimeoutError",
    "AsyncKaitenClient",
    "AsyncKaitenPlatformClient",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "CredentialError",
    "InternalServerError",
    "KaitenClient",
    "KaitenError",
    "KaitenModel",
    "KaitenPlatformClient",
    "NotFoundError",
    "NotGiven",
    "PaginationError",
    "PermissionDeniedError",
    "RateLimitError",
    "ServiceUnavailableError",
    "ThresholdExceededError",
    "UnprocessableEntityError",
    "WebhookPayloadError",
    "WebhookVerificationError",
    "__version__",
    "targeting",
    "types",
    "usage",
    "webhooks",
]


def __getattr__(name: str) -> Any:
    # The webhook event models are only loaded by the code that receives webhooks.
    if name == "webhooks":
        return importlib.import_module(f"{__name__}.webhooks")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
