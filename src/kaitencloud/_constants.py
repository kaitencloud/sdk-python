# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Defaults shared by both clients."""

from __future__ import annotations

from typing import Final

import httpx

DEFAULT_TIMEOUT: Final = httpx.Timeout(30.0, connect=10.0)
"""The timeout of the HTTP client a Kaiten client builds for itself."""

DEFAULT_MAX_RETRIES: Final = 2
"""How many times a failed request that is safe to repeat is retried by default."""

MAX_PAGE_SIZE: Final = 200
"""The largest page Kaiten's list endpoints accept.

A hard ceiling, not a hint: the endpoints declare ``maximum: 200`` and answer 201 with a 422.
Walking at this size is the fewest round trips a complete list can take.
"""

INITIAL_RETRY_DELAY: Final = 0.25
MAX_RETRY_DELAY: Final = 8.0
MAX_RETRY_AFTER: Final = 60.0

ENV_BASE_URL: Final = "KAITEN_BASE_URL"
ENV_TOKEN: Final = "KAITEN_AUTH_TOKEN"
ENV_PLATFORM_BASE_URL: Final = "KAITEN_PLATFORM_BASE_URL"
ENV_PLATFORM_TOKEN: Final = "KAITEN_PLATFORM_TOKEN"
