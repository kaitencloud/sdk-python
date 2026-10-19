# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Provider usage snapshots, never prompts, prices or transport code."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._ai import add_usage, from_anthropic, from_openai
from .types import AiRequestType, AiUsageParam

OPENAI_METHODS: dict[str, AiRequestType] = {
    "chat.completions.create": "COMPLETION",
    "responses.create": "COMPLETION",
    "embeddings.create": "EMBEDDING",
    "images.generate": "IMAGE_GENERATION",
    "audio.transcriptions.create": "AUDIO",
    "audio.speech.create": "AUDIO",
}
ANTHROPIC_METHODS: dict[str, AiRequestType] = {
    "messages.create": "COMPLETION",
    "messages.stream": "COMPLETION",
}


def get(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, Mapping) else getattr(value, name, default)


class UsageSnapshot:
    """Latest cumulative usage for one request; image completions are separate units."""

    def __init__(self, provider: str, operation: str) -> None:
        self.provider = provider
        self.operation = operation
        self.usage: AiUsageParam | None = None
        self.received = False
        self.completed = False
        self.failed = False
        self.images = 0

    def result(self, result: Any) -> AiUsageParam | None:
        usage = get(result, "usage")
        if usage is not None:
            self.usage = (
                from_anthropic(usage) if self.provider == "anthropic" else from_openai(usage)
            )
        if self.operation == "images.generate":
            images = get(result, "data")
            if images is not None:
                self.usage = {**(self.usage or {}), "units": len(images), "unit_type": "image"}
        # verbose_json transcriptions expose duration directly, not under usage.
        if self.operation == "audio.transcriptions.create" and usage is None:
            duration = get(result, "duration")
            if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                self.usage = {"duration_ms": max(round(duration * 1000), 0)}
        return self.usage

    def event(self, event: Any) -> None:
        self.received = True
        kind = get(event, "type")
        if self.provider == "anthropic":
            if kind == "message_start":
                self.result(get(event, "message"))
            elif kind == "message_delta":
                usage = get(event, "usage")
                if usage is not None:
                    # Deltas contain cumulative totals; absent/null fields keep the start value.
                    fields = {
                        "input_tokens": "input_tokens",
                        "cache_read_input_tokens": "cache_read_input_tokens",
                        "cache_creation_input_tokens": "cache_write_input_tokens",
                        "output_tokens": "output_tokens",
                    }
                    merged = dict(self.usage or {})
                    for source, target in fields.items():
                        count = get(usage, source)
                        if count is not None:
                            merged[target] = count
                    self.usage = merged  # type: ignore[assignment]
            elif kind == "message_stop":
                self.completed = True
            elif kind == "error":
                self.failed = True
            return
        if kind in ("response.completed", "response.incomplete", "response.failed"):
            self.result(get(event, "response"))
            self.completed = True
            self.failed = kind == "response.failed"
        elif kind == "image_generation.completed":
            self.images += 1
            normalised = from_openai(get(event, "usage"))
            self.usage = add_usage(self.usage, normalised)
            self.usage["units"] = self.images
            self.usage["unit_type"] = "image"
        elif kind == "transcript.text.done":
            self.result(event)
            self.completed = True
        else:
            usage = get(event, "usage")
            if usage is not None:
                self.usage = from_openai(usage)
            if kind == "error":
                self.failed = True
