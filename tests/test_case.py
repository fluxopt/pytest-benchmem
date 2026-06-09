from __future__ import annotations

import platform
from contextlib import contextmanager

import pytest

from benchkit import Case, measure

memray = pytest.importorskip("memray")
pytestmark = pytest.mark.skipif(
    platform.system() == "Windows", reason="memray unavailable on Windows"
)


def _cases():
    @contextmanager
    def case(n):
        data = list(range(n))  # setup — not measured
        yield lambda: [x * 2 for x in data]

    return [
        Case(id=f"double[n={n}]", dims={"op": "double", "n": n}, run=lambda n=n: case(n))
        for n in (1000, 10_000)
    ]


def test_measure_returns_samples_with_dims():
    samples = measure(_cases())
    assert {s.id for s in samples} == {"double[n=1000]", "double[n=10000]"}
    assert all(s.value >= 0 for s in samples)
    assert samples[0].dims["op"] == "double"


def test_select_filters_cases():
    samples = measure(_cases(), select=lambda c: c.dims["n"] == 1000)
    assert {s.id for s in samples} == {"double[n=1000]"}


def test_on_error_surfaces_failures():
    from contextlib import contextmanager

    from benchkit import Case

    @contextmanager
    def boom():
        yield lambda: (_ for _ in ()).throw(RuntimeError("nope"))

    errs = []
    samples = measure(
        [Case(id="bad", dims={}, run=boom)], on_error=lambda i, e: errs.append((i, str(e)))
    )
    assert samples == []
    assert errs == [("bad", "nope")]
