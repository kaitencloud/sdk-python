# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""Builders for feature flag variants, default variants and targeting rules.

::

    from kaitencloud import KaitenClient, targeting

    client.feature_flags.create(
        name="New checkout",
        type="boolean",
        variants=[targeting.variant("on", True), targeting.variant("off", False)],
        default_variant=targeting.fixed("off"),
        targetings=[
        targeting.rule("Growth plan", "__kaiten.license.familySlug == 'growth'", "on"),
            targeting.split_rule("Everyone else", "true", {"on": 20, "off": 80}),
        ],
    )

Rules are CEL expressions over the evaluation context, evaluated in order: the first that
matches decides, and a context no rule matches gets the default variant. The server fills the
reserved ``__kaiten`` namespace itself -- ``__kaiten.license.familySlug``,
``__kaiten.instance.metadata`` and so on -- so a rule can target on what a customer bought.
Target a plan by ``familySlug`` rather than ``slug``: the family's slug survives new versions,
while a version's changes every time one is published.

Splits are sticky: a subject is bucketed on the flag's key and its targeting key, so it keeps
its variant from one evaluation to the next, and one flag's rollout does not decide another's.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ._utils import format_datetime
from .types import DefaultVariantParam, RolloutStepParam, TargetingParam, VariantParam

__all__ = [
    "fixed",
    "rule",
    "schedule",
    "schedule_rule",
    "split",
    "split_rule",
    "step",
    "variant",
]


def variant(name: str, value: Any, *, description: str = "") -> VariantParam:
    """One possible value of a flag, e.g. ``variant("on", True)``."""
    return {"name": name, "value": value, "description": description}


def fixed(variant: str) -> DefaultVariantParam:
    """A default variant that always serves ``variant``."""
    return {"type": "basic", "value": variant}


def split(distribution: Mapping[str, int]) -> DefaultVariantParam:
    """A default variant that splits traffic by weight, e.g. ``split({"on": 20, "off": 80})``."""
    return {"type": "rollout_percentage", "distribution": _weights(distribution)}


def step(variant: str, percentage: int, at: datetime | str) -> RolloutStepParam:
    """One end of a scheduled rollout: ``variant`` gets ``percentage`` percent of traffic at ``at``."""
    if not 0 <= percentage <= 100:
        raise ValueError(f"percentage must be between 0 and 100, got {percentage}")
    return {"variant": variant, "percentage": percentage, "date": format_datetime(at)}


def schedule(*, start: RolloutStepParam, end: RolloutStepParam) -> DefaultVariantParam:
    """A default variant whose traffic moves linearly from ``start`` to ``end`` over time."""
    return {"type": "rollout_date", "start": start, "end": end}


def rule(name: str, expression: str, variant: str) -> TargetingParam:
    """A rule serving ``variant`` to every context the CEL ``expression`` matches."""
    return {"type": "basic", "name": name, "rule": expression, "variant": variant}


def split_rule(name: str, expression: str, distribution: Mapping[str, int]) -> TargetingParam:
    """A rule splitting the contexts ``expression`` matches between variants, by weight."""
    return {
        "type": "rollout_percentage",
        "name": name,
        "rule": expression,
        "distribution": _weights(distribution),
    }


def schedule_rule(
    name: str, expression: str, *, start: RolloutStepParam, end: RolloutStepParam
) -> TargetingParam:
    """A rule moving the contexts ``expression`` matches from ``start`` to ``end`` over time."""
    return {"type": "rollout_date", "name": name, "rule": expression, "start": start, "end": end}


def _weights(distribution: Mapping[str, int]) -> dict[str, int]:
    if not distribution:
        raise ValueError("a split needs at least one variant")
    for name, weight in distribution.items():
        if isinstance(weight, bool) or not isinstance(weight, int) or weight <= 0:
            raise ValueError(f"split weights are positive integers, got {name!r}: {weight!r}")
    return dict(distribution)
