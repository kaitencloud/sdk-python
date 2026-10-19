# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Optional provider entry points, imported only when a drop-in class is requested."""

from __future__ import annotations

import importlib
from typing import Any

from ._ai import Estimator
from ._async.ai import AsyncMeter
from ._async.client import AsyncKaitenClient
from ._async.providers import AsyncProvider
from ._sync.ai import Meter
from ._sync.client import KaitenClient
from ._sync.providers import Provider


def wrap(
    client: Any,
    kaiten: KaitenClient | AsyncKaitenClient,
    provider: str,
    *,
    instance: str,
    entitlement: str,
    estimator: Estimator | None = None,
) -> Any:
    if isinstance(kaiten, AsyncKaitenClient):
        return AsyncProvider(
            client,
            AsyncMeter(kaiten, instance=instance, entitlement=entitlement, estimator=estimator),
            provider,
        )
    return Provider(
        client,
        Meter(kaiten, instance=instance, entitlement=entitlement, estimator=estimator),
        provider,
    )


def drop_in(provider: str, name: str, module: str) -> type[Any]:
    try:
        base = getattr(importlib.import_module(provider), name)
    except ImportError as error:
        raise ImportError(f"Install kaitencloud[{provider}] to use {module}.{name}") from error

    def init(
        self: Any,
        *args: Any,
        kaiten: KaitenClient | AsyncKaitenClient | None = None,
        instance: str | None = None,
        entitlement: str | None = None,
        estimator: Estimator | None = None,
        **kwargs: Any,
    ) -> None:
        if "pool" in kwargs:
            raise TypeError("unexpected keyword argument 'pool'; use 'entitlement' instead")
        if kaiten is not None and (instance is None or entitlement is None):
            raise ValueError("instance and entitlement are required with kaiten")
        if kaiten is not None and name.startswith("Async") != isinstance(kaiten, AsyncKaitenClient):
            raise TypeError(
                "provider and Kaiten clients must both be synchronous or both asynchronous"
            )
        base.__init__(self, *args, **kwargs)
        if kaiten is not None:
            assert instance is not None
            assert entitlement is not None
            proxy = wrap(
                self,
                kaiten,
                provider,
                instance=instance,
                entitlement=entitlement,
                estimator=estimator,
            )
            roots = (
                ("chat", "responses", "embeddings", "images", "audio")
                if provider == "openai"
                else ("messages",)
            )
            resources = {root: getattr(proxy, root) for root in roots}
            for root, resource in resources.items():
                setattr(self, root, resource)
            # Copies must carry the existing pool meter rather than silently losing metering.
            for method in ("copy", "with_options"):
                original = getattr(base, method, None)
                if original is not None:

                    def copied(*args: Any, _original: Any = original, **kwargs: Any) -> Any:
                        copied_client = _original(self, *args, **kwargs)
                        return type(proxy)(copied_client, proxy._meter, provider)

                    setattr(self, method, copied)

    return type(name, (base,), {"__init__": init, "__module__": module})
