# Copyright 2026 KAITEN INC
# SPDX-License-Identifier: Apache-2.0

"""The arithmetic of entitlement enforcement, as the Kaiten API applies it.

A numeric grant carries two numbers -- its value and its overage allowance
(``limit_cap_exceeded_overage_percent``) -- and every boundary derives from them:

=================  ====================  =========================================
Overage percent    Meaning               A usage report is refused when usage is
=================  ====================  =========================================
``-1``             unlimited (value -1)  never
``0``              hard limit            above the value
``10``             soft limit, +10%      above the value plus 10% of it
=================  ====================  =========================================

These helpers compute the boundaries the server enforces, so an application can render a
meter, or check a report before sending it, without another round trip::

    from kaitencloud import usage

    grant = client.licenses.get_entitlement("growth", "seats")
    cap = usage.maximum_allowed_usage(grant.value.value, grant.limit_cap_exceeded_overage_percent)

A soft limit is not exhausted at its value: a customer with 100 seats and a 10% allowance is
served the 105th seat. :func:`percentage_used` reaches 100 where the customer consumed what
they bought, and keeps climbing through the allowance, while :func:`remaining` counts down to
where the server starts refusing.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "UNLIMITED",
    "accepts",
    "is_hard_limit",
    "is_soft_limit",
    "is_unlimited",
    "maximum_allowed_usage",
    "percentage_used",
    "remaining",
]

UNLIMITED: Final = -1
"""The grant value that means "no cap"."""


def is_unlimited(value: float) -> bool:
    """Whether a grant ``value`` is the unlimited sentinel."""
    return value == UNLIMITED


def maximum_allowed_usage(value: float, overage_percent: int | None = 0) -> float | None:
    """The most usage the API accepts against a grant: its value plus its allowance.

    ``None`` for an unlimited grant. Zero is a real cap, not an absence of one.
    """
    if is_unlimited(value) or value < 0:
        return None
    return value + value * max(overage_percent or 0, 0) / 100


def is_hard_limit(value: float, overage_percent: int | None) -> bool:
    """Whether usage is refused as soon as it exceeds the grant's value."""
    return not is_unlimited(value) and (overage_percent or 0) <= 0


def is_soft_limit(value: float, overage_percent: int | None) -> bool:
    """Whether usage may exceed the grant's value by an allowance before being refused."""
    return not is_unlimited(value) and (overage_percent or 0) > 0


def accepts(value: float, usage: float, overage_percent: int | None = 0) -> bool:
    """Whether the API accepts a report that leaves usage at ``usage``."""
    cap = maximum_allowed_usage(value, overage_percent)
    return cap is None or usage <= cap


def remaining(value: float, used: float, overage_percent: int | None = 0) -> float | None:
    """How much more can be used before reports are refused; ``None`` when unlimited."""
    cap = maximum_allowed_usage(value, overage_percent)
    return None if cap is None else max(cap - used, 0.0)


def percentage_used(value: float, used: float) -> float | None:
    """Usage as a percentage of the grant's value -- not of its cap, so it can exceed 100.

    ``None`` when the grant is unlimited or its value is zero.
    """
    if is_unlimited(value) or value <= 0:
        return None
    return used / value * 100
