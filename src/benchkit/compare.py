"""Text comparison of two snapshots — keyed on the opaque id."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from benchkit.snapshot import load_long_df


def compare_snapshots(a: str | Path, b: str | Path, *, out: TextIO | None = None) -> None:
    """Print a per-id table of ``a`` vs ``b`` with percent change.

    Works for any unit; mixing units raises (via :func:`load_long_df`). Ids
    present in only one snapshot show ``—``.
    """
    out = out or sys.stdout
    df, unit = load_long_df([Path(a), Path(b)])
    labels = df["snapshot"].drop_duplicates().tolist()
    la, lb = labels[0], labels[1]
    wide = df.pivot(index="id", columns="snapshot", values="value")

    print(f"\n{'id':<70} {la:>12} {lb:>12} {'change':>10}  ({unit})", file=out)
    print("-" * 108, file=out)
    for test_id in sorted(wide.index):
        va = wide.at[test_id, la] if la in wide.columns else None
        vb = wide.at[test_id, lb] if lb in wide.columns else None
        va = None if va is None or va != va else va  # noqa: PLR0124 — NaN check
        vb = None if vb is None or vb != vb else vb
        a_str = f"{va:.4g}" if va is not None else "—"
        b_str = f"{vb:.4g}" if vb is not None else "—"
        change = f"{(vb - va) / va * 100:+.1f}%" if va and vb and va > 0 else "—"
        short = test_id.split("::")[-1]
        print(f"{short:<70} {a_str:>12} {b_str:>12} {change:>10}", file=out)
    print(file=out)
