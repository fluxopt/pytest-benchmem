"""pytest plugin — peak-memory alongside pytest-benchmark timing.

pytest-benchmark times your code but can't measure memory. This plugin adds a
memray peak-memory pass *to the same test, in the same run*, stored in
pytest-benchmark's own JSON (``extra_info.benchmem``) so timing and memory share
one node id. Two ways in:

- The ``benchmark_memory`` fixture — explicit, per-test::

      def test_build(benchmark_memory):
          benchmark_memory(build_model, 1000)

- The ``--benchmark-memory`` flag — augments the stock ``benchmark`` fixture, so
  an *existing* pytest-benchmark suite records memory with no code change::

      pytest --benchmark-only --benchmark-memory

Either way the two passes never overlap: pytest-benchmark times the action with
no tracker installed, then memray measures peak on a separate, untimed call — so
the allocator hooks cost the timing numbers nothing. Memory comes back out via
:func:`pytest_benchmem.memory_from_pytest_benchmark` into the unit-aware
``plot`` / ``compare``.

Registered via the ``pytest11`` entry point — installing pytest-benchmem is enough.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

import pytest

from pytest_benchmem.memray import MemoryResult, measure_memory
from pytest_benchmem.snapshot import BENCHMEM_KEY

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

#: Name of the per-test marker: ``@pytest.mark.benchmem(repeats=N)``.
MARKER = "benchmem"


def _repeats_from_node(node: Any, default: int = 1) -> int:
    """Read ``repeats`` off a test's ``@pytest.mark.benchmem`` marker, if present."""
    marker = node.get_closest_marker(MARKER) if node is not None else None
    if marker is not None and "repeats" in marker.kwargs:
        return max(1, int(marker.kwargs["repeats"]))
    return default


def _record_memory(
    benchmark: BenchmarkFixture, action: Callable[[], Any], *, repeats: int = 1
) -> MemoryResult:
    """Memory-profile ``action`` into ``benchmark.extra_info["benchmem"]``, once.

    Idempotent: if a blob is already recorded for this benchmark (e.g. the
    ``--benchmark-memory`` patch and the explicit fixture both fire), reuse it
    rather than measuring twice.
    """
    existing = benchmark.extra_info.get(BENCHMEM_KEY)
    if isinstance(existing, Mapping):
        return MemoryResult(
            int(existing["peak_bytes"]),
            int(existing["peak_bytes_max"]),
            int(existing["allocations"]),
            int(existing.get("total_bytes", 0)),
            int(existing["repeats"]),
        )
    result = measure_memory(action, repeats=repeats)
    benchmark.extra_info[BENCHMEM_KEY] = result.as_dict()
    return result


class MemoryBenchmark:
    """Callable wrapper that times via pytest-benchmark, then memory-profiles.

    Mirrors the ``benchmark`` fixture's surface (``__call__`` and ``pedantic``)
    so it's a drop-in for tests that want memory too. After a call, the measured
    memory is on :attr:`result` (and :attr:`peak_bytes`) and in the benchmark's
    ``extra_info["benchmem"]``.
    """

    def __init__(self, benchmark: BenchmarkFixture, *, repeats: int = 1) -> None:
        self._benchmark = benchmark
        self._repeats = repeats
        self.result: MemoryResult | None = None

    @property
    def peak_bytes(self) -> int | None:
        """Peak memory (bytes) from the last call, or ``None`` before any call."""
        return None if self.result is None else self.result.peak_bytes

    @property
    def extra_info(self) -> dict[str, Any]:
        """pytest-benchmark's per-benchmark metadata dict.

        Set scalars here to attach analysis dims — ``benchmark_memory.extra_info["op"]
        = "sort"`` — and pytest-benchmem's readers pick them up as dims alongside the
        parametrize params. The memory blob is stored here too, under ``benchmem``.
        """
        return self._benchmark.extra_info

    def __call__(self, function_to_benchmark: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Time ``function_to_benchmark(*args, **kwargs)``, then record its peak memory."""
        result = self._benchmark(function_to_benchmark, *args, **kwargs)
        self.result = _record_memory(
            self._benchmark, lambda: function_to_benchmark(*args, **kwargs), repeats=self._repeats
        )
        return result

    def pedantic(
        self,
        target: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: Mapping[str, Any] | None = None,
        setup: Callable[[], Any] | None = None,
        rounds: int = 1,
        warmup_rounds: int = 0,
        iterations: int = 1,
    ) -> Any:
        """Like :meth:`pytest_benchmark.fixture.BenchmarkFixture.pedantic`, plus a memory pass.

        ``setup`` runs untracked before the measured call (and, if it returns
        ``(args, kwargs)``, supplies them) — matching pytest-benchmark, and
        giving back the untimed-setup/measured-action split cleanly.
        """
        kwargs = dict(kwargs or {})
        result = self._benchmark.pedantic(  # type: ignore[no-untyped-call]
            target,
            args=args,
            kwargs=kwargs,
            setup=setup,
            rounds=rounds,
            warmup_rounds=warmup_rounds,
            iterations=iterations,
        )
        self.result = _record_memory(
            self._benchmark, _pedantic_action(target, args, kwargs, setup), repeats=self._repeats
        )
        return result


def _pedantic_action(
    target: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
    setup: Callable[[], Any] | None,
) -> Callable[[], Any]:
    """Build the zero-arg measured action for a pedantic call, honoring ``setup``."""

    def action() -> Any:
        call_args, call_kwargs = args, dict(kwargs)
        if setup is not None:
            produced = setup()
            if produced is not None:
                call_args, call_kwargs = produced
        return target(*call_args, **call_kwargs)

    return action


@pytest.fixture
def benchmark_memory(
    benchmark: BenchmarkFixture, request: pytest.FixtureRequest
) -> MemoryBenchmark:
    """Time *and* peak-memory-profile a callable in one pytest-benchmark test.

    Depends on the ``benchmark`` fixture, so timing rides pytest-benchmark fully;
    the memray memory pass is added on top and stored in the same entry. The
    ``@pytest.mark.benchmem(repeats=N)`` marker sets min-of-N passes for this test.
    For an existing suite, prefer the ``--benchmark-memory`` flag over rewriting tests.
    """
    return MemoryBenchmark(benchmark, repeats=_repeats_from_node(request.node))


# --- --benchmark-memory: augment the stock `benchmark` fixture --------------------

_PATCHED: tuple[Any, Any, Any] | None = None


#: pedantic kwargs the patch passes through — guard against a version that drops one.
_PEDANTIC_PARAMS = frozenset({"args", "kwargs", "setup", "rounds", "warmup_rounds", "iterations"})


def _patch_compatible(fixture_cls: Any) -> bool:
    """True if ``BenchmarkFixture.pedantic`` still takes the kwargs the patch passes.

    (``__call__`` is invoked positionally, so it needs no signature guard.)
    """
    try:
        pedantic_params = set(inspect.signature(fixture_cls.pedantic).parameters)
    except (TypeError, ValueError, AttributeError):
        return False
    return pedantic_params >= _PEDANTIC_PARAMS


def _install_auto_memory() -> None:
    """Wrap ``BenchmarkFixture.__call__``/``.pedantic`` to also record peak memory."""
    global _PATCHED
    if _PATCHED is not None:
        return
    import pytest_benchmark
    from pytest_benchmark.fixture import BenchmarkFixture

    if not _patch_compatible(BenchmarkFixture):
        raise pytest.UsageError(
            f"--benchmark-memory: pytest-benchmark {pytest_benchmark.__version__} has a "
            f"BenchmarkFixture.pedantic() signature pytest-benchmem doesn't recognize, so "
            f"the auto-memory patch can't apply safely. Either:\n"
            f"  - install a pytest-benchmark version pytest-benchmem supports, or\n"
            f"  - drop --benchmark-memory (timing still runs normally), or\n"
            f"  - report it so we add support: "
            f"https://github.com/fluxopt/pytest-benchmem/issues"
        )

    orig_init = BenchmarkFixture.__init__
    orig_call = BenchmarkFixture.__call__
    orig_pedantic = BenchmarkFixture.pedantic

    def init(self: BenchmarkFixture, node: Any, *a: Any, **k: Any) -> None:
        orig_init(self, node, *a, **k)  # type: ignore[no-untyped-call]
        setattr(self, "_benchmem_node", node)  # noqa: B010 — stash for the marker read

    def _repeats(self: BenchmarkFixture) -> int:
        return _repeats_from_node(getattr(self, "_benchmem_node", None))

    def call(
        self: BenchmarkFixture, function_to_benchmark: Callable[..., Any], *a: Any, **k: Any
    ) -> Any:
        result = orig_call(self, function_to_benchmark, *a, **k)  # type: ignore[no-untyped-call]
        _record_memory(self, lambda: function_to_benchmark(*a, **k), repeats=_repeats(self))
        return result

    def pedantic(
        self: BenchmarkFixture,
        target: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: Mapping[str, Any] | None = None,
        setup: Callable[[], Any] | None = None,
        rounds: int = 1,
        warmup_rounds: int = 0,
        iterations: int = 1,
    ) -> Any:
        kwargs = dict(kwargs or {})
        result = orig_pedantic(  # type: ignore[no-untyped-call]
            self,
            target,
            args=args,
            kwargs=kwargs,
            setup=setup,
            rounds=rounds,
            warmup_rounds=warmup_rounds,
            iterations=iterations,
        )
        _record_memory(self, _pedantic_action(target, args, kwargs, setup), repeats=_repeats(self))
        return result

    BenchmarkFixture.__init__ = init  # type: ignore[method-assign]
    BenchmarkFixture.__call__ = call  # type: ignore[method-assign]
    BenchmarkFixture.pedantic = pedantic  # type: ignore[method-assign,assignment]
    _PATCHED = (orig_init, orig_call, orig_pedantic)


def _remove_auto_memory() -> None:
    global _PATCHED
    if _PATCHED is None:
        return
    from pytest_benchmark.fixture import BenchmarkFixture

    BenchmarkFixture.__init__, BenchmarkFixture.__call__, BenchmarkFixture.pedantic = _PATCHED  # type: ignore[method-assign]
    _PATCHED = None


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--benchmark-memory`` flags."""
    group = parser.getgroup("pytest-benchmem", "peak-memory benchmarking")
    group.addoption(
        "--benchmark-memory",
        action="store_true",
        default=False,
        help="Record peak memory (memray) for every benchmark() call, "
        "not only benchmark_memory — no test changes needed.",
    )
    group.addoption(
        "--benchmark-memory-compare",
        action="store",
        nargs="?",
        default=False,
        const=True,
        metavar="REF",
        help="Compare this run's peak memory against a prior saved run "
        "(pytest-benchmark storage ref like 0001, or the latest if no value); "
        "prints a per-id memory delta in the summary.",
    )
    group.addoption(
        "--benchmark-memory-compare-fail",
        action="append",
        metavar="FIELD:THRESHOLD",
        help="Fail the session on a memory regression (repeatable): "
        "peak:10% / peak:5MiB / allocations:5%. Implies --benchmark-memory-compare.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``benchmem`` marker; patch ``benchmark`` if ``--benchmark-memory`` is set."""
    config.addinivalue_line(
        "markers",
        "benchmem(repeats=N): pytest-benchmem peak-memory options — "
        "repeats sets the number of memray passes (the reported peak is the min).",
    )
    if config.getoption("--benchmark-memory"):
        _install_auto_memory()


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore the stock ``benchmark`` fixture after the session."""
    _remove_auto_memory()


# --- --benchmark-memory-compare[-fail]: inline memory gating ---------------------


class MemoryRegression(Exception):
    """Raised from the terminal summary to fail a run on a memory regression."""


def _compare_requested(config: pytest.Config) -> tuple[object, list[str]]:
    """``(compare_ref, fail_exprs)`` — ``compare_ref`` is False/True/str; fail implies compare."""
    compare = config.getoption("--benchmark-memory-compare")
    fail_exprs = config.getoption("--benchmark-memory-compare-fail") or []
    if fail_exprs and compare is False:
        compare = True  # --…-fail with no explicit --…-compare means compare against latest
    return compare, fail_exprs


def _memory_blobs(benchmarks: Any) -> dict[str, dict[str, Any]]:
    """``{fullname: benchmem-blob}`` for the benchmarks that recorded memory."""
    blobs: dict[str, dict[str, Any]] = {}
    for bm in benchmarks:
        extra = getattr(bm, "extra_info", None)
        blob = extra.get(BENCHMEM_KEY) if isinstance(extra, Mapping) else None
        if isinstance(blob, Mapping):
            blobs[bm.fullname] = dict(blob)
    return blobs


def _load_baseline(storage: Any, compare: object) -> tuple[str | None, dict[str, dict[str, Any]]]:
    """Resolve a baseline via pytest-benchmark storage → ``(label, {id: blob})``.

    Mirrors pytest-benchmark's own ref handling: ``True`` → the latest run, a
    string → runs matching that ref (the most recent wins).
    """
    loaded = list(storage.load()) if compare is True else list(storage.load(compare))
    if not loaded:
        return None, {}
    path, data = loaded[-1]
    blobs: dict[str, dict[str, Any]] = {}
    for bench in data.get("benchmarks", []):
        blob = bench.get("extra_info", {}).get(BENCHMEM_KEY)
        if isinstance(blob, Mapping):
            blobs[bench["fullname"]] = dict(blob)
    return str(path), blobs


def pytest_sessionstart(session: pytest.Session) -> None:
    """Snapshot the comparison baseline *before* this run is saved (no self-compare)."""
    config = session.config
    compare, fail_exprs = _compare_requested(config)
    if compare is False and not fail_exprs:
        return
    bs = getattr(config, "_benchmarksession", None)
    if bs is None:  # pytest-benchmark not active for this run
        return
    try:
        label, blobs = _load_baseline(bs.storage, compare)
    except Exception as exc:  # noqa: BLE001 — storage problems shouldn't crash the session
        label, blobs = None, {}
        bs.logger.warning(f"benchmem: could not load comparison baseline ({exc}).")
    config._benchmem_baseline = (label, blobs)  # type: ignore[attr-defined]


def pytest_terminal_summary(terminalreporter: Any, config: pytest.Config) -> None:
    """Print the memory comparison and fail the run if a threshold is exceeded."""
    compare, fail_exprs = _compare_requested(config)
    if compare is False and not fail_exprs:
        return

    from pytest_benchmem.compare import (
        _BLOB_FIELD,
        Regression,
        memory_regressions,
        parse_threshold,
    )
    from pytest_benchmem.snapshot import human_bytes

    thresholds = []
    if fail_exprs:
        try:
            thresholds = [parse_threshold(expr) for expr in fail_exprs]
        except ValueError as exc:
            raise pytest.UsageError(str(exc)) from exc
        bad = [t.field for t in thresholds if t.field not in _BLOB_FIELD]
        if bad:
            raise pytest.UsageError(
                f"--benchmark-memory-compare-fail can't gate on {', '.join(bad)}; "
                f"use {' or '.join(_BLOB_FIELD)} "
                f"(timing is pytest-benchmark's --benchmark-compare-fail)"
            )

    bs = getattr(config, "_benchmarksession", None)
    current = _memory_blobs(bs.benchmarks) if bs is not None else {}
    default: tuple[str | None, dict[str, dict[str, Any]]] = (None, {})
    label, baseline = getattr(config, "_benchmem_baseline", default)

    write = terminalreporter.write_line
    if not current:
        write(
            "benchmem-compare: no memory recorded this run "
            "(use benchmark_memory or --benchmark-memory)."
        )
        return
    if not baseline:
        write("benchmem-compare: no prior run with memory to compare against.")
        return

    write(f"\nMemory vs {label} (peak):")
    for test_id in sorted(current.keys() & baseline.keys()):
        vb = float(baseline[test_id].get("peak_bytes", "nan"))
        vh = float(current[test_id].get("peak_bytes", "nan"))
        pct = f"{(vh - vb) / vb * 100:+.1f}%" if vb > 0 else "—"
        short = test_id.split("::")[-1]
        write(f"  {short}: {human_bytes(vb)} → {human_bytes(vh)} ({pct})")

    if thresholds:
        regressions: list[Regression] = memory_regressions(baseline, current, thresholds)
        if regressions:
            write("Memory regressions over threshold:")
            for reg in regressions:
                write(reg.format())
            raise MemoryRegression(f"{len(regressions)} memory regression(s) over threshold.")
