"""Empirical scaling fit — the exponent ``x`` in ``value ≈ c·nˣ`` over a size sweep.

A log-log least-squares of a metric (peak memory or time) against a numeric dim
(``n``), per benchmark family, so "this phase is ~O(n^1.9)" falls out of a sweep —
catching *complexity* regressions a point-to-point compare misses (order-of-growth
vs constant-factor). The exponent comes with R² and the point count, so a thin or
noisy fit is visible rather than silently trusted.

A *family* is one benchmark swept over the numeric dim: keyed by the id minus its
parametrize bracket (``test_sort[n=10]`` → ``test_sort``) plus the non-x dims, so
two functions — or two ``op`` values — sweeping the same ``n`` stay separate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    import pandas as pd


class ScalingFit(NamedTuple):
    """One family's fit: empirical ``exponent`` with its ``r2`` and point count ``n``."""

    family: str
    exponent: float
    r2: float
    n: int


def _numeric_dims(df: pd.DataFrame) -> list[str]:
    """Dim columns whose non-null values are all real numbers (not bool)."""
    fixed = ("snapshot", "id", "value")
    dims = [c for c in df.columns if c not in fixed]
    out = []
    for d in dims:
        vals = df[d].dropna()
        if (
            len(vals)
            and vals.map(lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)).all()
        ):
            out.append(d)
    return out


def infer_x(df: pd.DataFrame) -> str:
    """The lone numeric dim to fit against, or raise if it isn't unambiguous."""
    nums = _numeric_dims(df)
    if len(nums) != 1:
        raise ValueError(f"scaling needs exactly one numeric dim for x (found {nums}); pass x=")
    return nums[0]


def _label(family: str, dims: dict[str, object]) -> str:
    extra = [f"{k}={v}" for k, v in dims.items() if v == v]  # drop NaN
    return family + (f"[{','.join(extra)}]" if extra else "")


def fit_power_law(df: pd.DataFrame, *, x: str | None = None) -> list[ScalingFit]:
    """Fit ``value ≈ c·xᵏ`` per family → exponents (k) with R² and point count.

    ``x`` is the numeric dim to fit against (inferred from the lone numeric dim if
    omitted). Families with fewer than 2 points, or non-positive ``x``/``value``,
    are dropped. Sorted by family.
    """
    import numpy as np

    if x is None:
        x = infer_x(df)
    other_dims = [c for c in df.columns if c not in ("snapshot", "id", "value", x)]

    work = df.dropna(subset=[x, "value"]).copy()
    work = work[(work[x] > 0) & (work["value"] > 0)]
    work["_family"] = work["id"].astype(str).str.split("[", n=1).str[0]

    keys = ["_family", *other_dims]
    fits: list[ScalingFit] = []
    for key, group in work.groupby(keys, dropna=False, sort=True):
        if len(group) < 2:  # need at least 2 points for a line
            continue
        keyvals = key if isinstance(key, tuple) else (key,)
        km = dict(zip(keys, keyvals, strict=True))
        lx = np.log(group[x].to_numpy(dtype=float))
        ly = np.log(group["value"].to_numpy(dtype=float))
        coeffs = np.polyfit(lx, ly, 1)
        slope, intercept = float(coeffs[0]), float(coeffs[1])
        pred = slope * lx + intercept
        ss_res = float(np.sum((ly - pred) ** 2))
        ss_tot = float(np.sum((ly - ly.mean()) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
        family = str(km.pop("_family"))
        fits.append(ScalingFit(_label(family, km), slope, r2, len(group)))

    return sorted(fits, key=lambda f: f.family)
