from __future__ import annotations

import platform
from contextlib import contextmanager

import pytest

from peakbench import Case, measure

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


def test_filter_before_convert():
    # Selection is the consumer's job, done before building Cases: keep your own
    # rich source, filter it, map only survivors to Case. measure() runs all it's handed.
    rich = [{"n": n, "skip": n != 1000} for n in (1000, 10_000)]

    @contextmanager
    def case(n):
        data = list(range(n))
        yield lambda: [x * 2 for x in data]

    cases = [
        Case(id=f"double[n={c['n']}]", dims={"n": c["n"]}, run=lambda n=c["n"]: case(n))
        for c in rich
        if not c["skip"]
    ]
    samples = measure(cases)
    assert {s.id for s in samples} == {"double[n=1000]"}


def test_build_once_runs_setup_action_teardown():
    from peakbench import build_once

    events = []

    def setup():
        events.append("setup")
        return [1, 2, 3]

    factory = build_once(
        setup,
        lambda data: events.append(f"action:{sum(data)}"),
        teardown=lambda _data: events.append("teardown"),
    )
    with factory() as action:
        assert events == ["setup"]  # action not yet run, teardown not yet run
        action()
    assert events == ["setup", "action:6", "teardown"]


def test_build_once_teardown_runs_on_action_error():
    from peakbench import build_once

    torn = []

    def boom(_obj):
        raise RuntimeError("nope")

    factory = build_once(lambda: object(), boom, teardown=lambda _o: torn.append(True))
    with pytest.raises(RuntimeError, match="nope"), factory() as action:
        action()
    assert torn == [True]


def test_on_error_surfaces_failures():
    from contextlib import contextmanager

    from peakbench import Case

    @contextmanager
    def boom():
        yield lambda: (_ for _ in ()).throw(RuntimeError("nope"))

    errs = []
    samples = measure(
        [Case(id="bad", dims={}, run=boom)], on_error=lambda i, e: errs.append((i, str(e)))
    )
    assert samples == []
    assert errs == [("bad", "nope")]
