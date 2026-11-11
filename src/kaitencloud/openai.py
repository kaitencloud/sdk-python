# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Optional openai drop-in clients and existing-client delegation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ._ai import Estimator, ProviderVendorCostOf
from ._async.ai import CommitFailureHandler
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
    vendor_cost: ProviderVendorCostOf | None = None,
    on_commit_failure: CommitFailureHandler | None = None,
) -> Any:
    """Meter the allow-list on an existing client; unlisted methods stay provider-owned.

    ``vendor_cost`` reports what each call cost at the vendor, from your own price table or
    the provider's response: the SDK knows no price. ``on_commit_failure`` receives a commit
    that failed after its retries -- :class:`~kaitencloud.AiCommitFailedError` -- instead of
    the call raising it.
    """
    return wrap(
        client,
        kaiten,
        "openai",
        instance=instance,
        entitlement=entitlement,
        estimator=estimator,
        vendor_cost=vendor_cost,
        on_commit_failure=on_commit_failure,
    )


def __getattr__(name: str) -> Any:
    if name in ("OpenAI", "AsyncOpenAI"):
        client_type = drop_in("openai", name, __name__)
        globals()[name] = client_type
        return client_type
    raise AttributeError(name)
