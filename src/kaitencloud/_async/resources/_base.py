# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from .._http import AsyncAPIClient

__all__ = ["AsyncResource"]


class AsyncResource:
    """Base class of a resource namespace, such as ``client.customers``."""

    __slots__ = ("_api",)

    def __init__(self, api: AsyncAPIClient) -> None:
        self._api = api

    def __repr__(self) -> str:
        return f"<{type(self).__name__} base_url={self._api.base_url!r}>"
