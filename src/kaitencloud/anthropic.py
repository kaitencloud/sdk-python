# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Optional anthropic drop-in clients and existing-client delegation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._ai import Estimator
from ._async.client import AsyncKaitenClient
from ._provider_clients import drop_in, wrap
from ._sync.client import KaitenClient

if TYPE_CHECKING:
    Anthropic: type[Any]
    AsyncAnthropic: type[Any]

__all__ = ["Anthropic", "AsyncAnthropic", "wrap_anthropic"]


def wrap_anthropic(
    client: Any,
    *,
    kaiten: KaitenClient | AsyncKaitenClient,
    instance: str,
    pool: str,
    estimator: Estimator | None = None,
) -> Any:
    """Meter the allow-list on an existing client; unlisted methods stay provider-owned."""
    return wrap(client, kaiten, "anthropic", instance=instance, pool=pool, estimator=estimator)


def __getattr__(name: str) -> Any:
    if name in ("Anthropic", "AsyncAnthropic"):
        client_type = drop_in("anthropic", name, __name__)
        globals()[name] = client_type
        return client_type
    raise AttributeError(name)
