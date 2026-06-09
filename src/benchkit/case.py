"""The atomic primitive: a :class:`Case` — one measurable unit of work.

Everything downstream (the memray engine, snapshots, plots) consumes only
``Case``; how cases are *generated* is the consumer's business. A case is a
context manager so setup (build inputs, scratch files) runs untimed/untracked
before the measured ``action`` and teardown runs after::

    @contextmanager
    def build_case(n):
        data = make_input(n)            # setup — not measured
        yield lambda: transform(data)   # the measured action

    Case(id="transform[n=1000]", dims={"op": "transform", "n": 1000},
         run=lambda: build_case(1000))
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import NamedTuple

#: A value of a dim axis — categorical (str) or numeric (int/float).
DimValue = str | int | float

#: A zero-arg callable doing the work that gets timed / memory-tracked.
Action = Callable[[], object]

#: A factory returning a fresh context manager that yields an :data:`Action`.
CaseFactory = Callable[[], AbstractContextManager[Action]]


class Case(NamedTuple):
    """One measurable unit of work.

    - ``id``  — stable identity, the key in snapshots (and, in pytest, the
      node id CodSpeed tracks). Opaque to benchkit.
    - ``dims`` — structured axes for analysis (e.g. ``{"op": "to_lp",
      "subject": "basic", "n": 10}``). Plots facet/scale by these instead of
      parsing the id.
    - ``run`` — a factory returning a context manager: setup → yield the
      measured ``action`` → teardown.
    """

    id: str
    dims: Mapping[str, DimValue]
    run: CaseFactory
