"""Shared display primitives for the terminal tables — byte/count rendering, unit
hoisting, best/worst colour, and growth deltas.

These are the small, repeatedly-needed bits the table renderers (``tables``,
``combined``) and the text comparison (``compare``) all reach for, gathered in one
place so a cell renders the same wherever it appears and there is a single spot to
adjust a rounding policy or colour rule. :func:`_human_bytes` (the standalone IEC
*string*, e.g. ``4.1 MiB``) lives in :mod:`pytest_benchmem.snapshot` — it is a
different shape (auto-scaled label, not a bare cell in a hoisted unit).
"""

from __future__ import annotations

from collections.abc import Iterable

#: Byte units in ascending order — each a ``(name, divisor)``. :func:`byte_unit`
#: walks these to hoist one unit into a column header so cells stay bare numbers.
_BYTE_STEPS = (("KiB", 1024.0), ("MiB", 1024.0**2), ("GiB", 1024.0**3), ("TiB", 1024.0**4))


def byte_unit(values: Iterable[float]) -> tuple[str, float]:
    """Unit ``(name, divisor)`` for a byte column, anchored on its **smallest positive**
    value so the smallest cell stays readable (rather than collapsing to ``0.00`` under a
    unit hoisted from the largest). One unit hoists into the header; cells stay comparable
    bare numbers — the same min-anchored scaling pytest-benchmark uses for its time column.
    """
    positives = [v for v in values if v > 0]
    anchor = min(positives) if positives else 0.0
    name, factor = "B", 1.0
    for step_name, step_factor in _BYTE_STEPS:
        if anchor >= step_factor:
            name, factor = step_name, step_factor
    return name, factor


def fmt_bytes(value: float, factor: float) -> str:
    """A byte value rendered bare in a column's unit (whole ``B``, else 2 decimals)."""
    return f"{value:,.0f}" if factor == 1.0 else f"{value / factor:,.2f}"


def fmt_count(value: float) -> str:
    """A thousands-separated integer count."""
    return f"{int(value):,}"


def fmt_label(value: float) -> str:
    """A numeric label readout: a thousands-separated integer when the value is integral
    (the common count case), else 4 significant figures — never silently truncated.
    """
    return fmt_count(value) if float(value).is_integer() else f"{value:,.4g}"


def rank_style(value: float | None, best: float | None, worst: float | None) -> str | None:
    """Green for the group's best (smallest) value, red for the worst, else unstyled.

    ``None`` for any missing input (a row with nothing to contrast against).
    """
    if value is None or best is None or worst is None:
        return None
    if value == best:
        return "green"
    if value == worst:
        return "red"
    return None


def signed_pct(pct: float) -> str:
    """A signed percent like ``+22.0%`` / ``-50.0%`` — but a plain ``0.0%`` when it rounds
    to zero, so sub-threshold noise never shows a misleading ``+0.0%`` / ``-0.0%`` sign.
    """
    return "0.0%" if round(pct, 1) == 0 else f"{pct:+.1f}%"


def growth(base: float, current: float) -> tuple[str, str | None]:
    """``(Δ%-string, style)`` for ``current`` vs ``base`` — red on growth, green on shrink.

    A non-positive baseline has no meaningful ratio, so the delta is ``—`` and unstyled.
    """
    if base <= 0:
        return "—", None
    pct = (current - base) / base * 100
    return signed_pct(pct), "red" if current > base else "green" if current < base else None
