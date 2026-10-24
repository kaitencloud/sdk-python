# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Optional openai drop-in clients and existing-client delegation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._ai import Estimator
from ._async.client import AsyncKaitenClient
from ._provider_clients import drop_in, wrap
from ._sync.client import KaitenClient

if TYPE_CHECKING:
    OpenAI: type[Any]
    AsyncOpenAI: type[Any]

__all__ = ["AsyncOpenAI", "OpenAI", "wrap_openai"]


def wrap_openai(
    client: Any,
    *,
    kaiten: KaitenClient | AsyncKaitenClient,
    instance: str,
    entitlement: str,
    estimator: Estimator | None = None,
) -> Any:
    """Meter the allow-list on an existing client; unlisted methods stay provider-owned."""
    return wrap(
        client, kaiten, "openai", instance=instance, entitlement=entitlement, estimator=estimator
    )


def __getattr__(name: str) -> Any:
    if name in ("OpenAI", "AsyncOpenAI"):
        client_type = drop_in("openai", name, __name__)
        globals()[name] = client_type
        return client_type
    raise AttributeError(name)
