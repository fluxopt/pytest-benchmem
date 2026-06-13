"""pytest plugin — peak-memory alongside pytest-benchmark timing.

pytest-benchmark times your code but can't measure memory. This plugin adds a
memray peak-memory pass *to the same test, in the same run*, stored in
pytest-benchmark's own JSON (``extra_info.peak_mib``) so timing and memory share
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

from pytest_benchmem.memray import measure_peak

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

#: Key under which the peak (MiB) is written into pytest-benchmark ``extra_info``.
PEAK_KEY = "peak_mib"


def _record_peak(
    benchmark: BenchmarkFixture, action: Callable[[], Any], *, repeats: int = 1
) -> float:
    """Memory-profile ``action`` into ``benchmark.extra_info[PEAK_KEY]``, once.

    Idempotent: if a peak is already recorded for this benchmark (e.g. the
    ``--benchmark-memory`` patch and the explicit fixture both fire), reuse it
    rather than measuring twice.
    """
    existing = benchmark.extra_info.get(PEAK_KEY)
    if existing is not None:
        return float(existing)
    peak = measure_peak(action, repeats=repeats)
    benchmark.extra_info[PEAK_KEY] = peak
    return peak


class MemoryBenchmark:
    """Callable wrapper that times via pytest-benchmark, then memory-profiles.

    Mirrors the ``benchmark`` fixture's surface (``__call__`` and ``pedantic``)
    so it's a drop-in for tests that want memory too. After a call, the peak is
    on :attr:`peak_mib` and in the benchmark's ``extra_info``.
    """

    def __init__(self, benchmark: BenchmarkFixture, *, repeats: int = 1) -> None:
        self._benchmark = benchmark
        self._repeats = repeats
        self.peak_mib: float | None = None

    @property
    def extra_info(self) -> dict[str, Any]:
        """pytest-benchmark's per-benchmark metadata dict.

        Set scalars here to attach analysis dims — ``benchmark_memory.extra_info["op"]
        = "sort"`` — and pytest-benchmem's readers pick them up as dims alongside the
        parametrize params. The peak is stored here too, under ``peak_mib``.
        """
        return self._benchmark.extra_info

    def __call__(self, function_to_benchmark: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Time ``function_to_benchmark(*args, **kwargs)``, then record its peak memory."""
        result = self._benchmark(function_to_benchmark, *args, **kwargs)
        self.peak_mib = _record_peak(
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
        self.peak_mib = _record_peak(
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
def benchmark_memory(benchmark: BenchmarkFixture) -> MemoryBenchmark:
    """Time *and* peak-memory-profile a callable in one pytest-benchmark test.

    Depends on the ``benchmark`` fixture, so timing rides pytest-benchmark fully;
    the memray memory pass is added on top and stored in the same entry. For an
    existing suite, prefer the ``--benchmark-memory`` flag over rewriting tests.
    """
    return MemoryBenchmark(benchmark)


# --- --benchmark-memory: augment the stock `benchmark` fixture --------------------

_PATCHED: tuple[Any, Any] | None = None


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

    orig_call = BenchmarkFixture.__call__
    orig_pedantic = BenchmarkFixture.pedantic

    def call(
        self: BenchmarkFixture, function_to_benchmark: Callable[..., Any], *a: Any, **k: Any
    ) -> Any:
        result = orig_call(self, function_to_benchmark, *a, **k)  # type: ignore[no-untyped-call]
        _record_peak(self, lambda: function_to_benchmark(*a, **k))
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
        _record_peak(self, _pedantic_action(target, args, kwargs, setup))
        return result

    BenchmarkFixture.__call__ = call  # type: ignore[method-assign]
    BenchmarkFixture.pedantic = pedantic  # type: ignore[method-assign,assignment]
    _PATCHED = (orig_call, orig_pedantic)


def _remove_auto_memory() -> None:
    global _PATCHED
    if _PATCHED is None:
        return
    from pytest_benchmark.fixture import BenchmarkFixture

    BenchmarkFixture.__call__, BenchmarkFixture.pedantic = _PATCHED  # type: ignore[method-assign]
    _PATCHED = None


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the ``--benchmark-memory`` flag."""
    group = parser.getgroup("pytest-benchmem", "peak-memory benchmarking")
    group.addoption(
        "--benchmark-memory",
        action="store_true",
        default=False,
        help="Record peak memory (memray) for every benchmark() call, "
        "not only benchmark_memory — no test changes needed.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Patch the stock ``benchmark`` fixture when ``--benchmark-memory`` is set."""
    if config.getoption("--benchmark-memory"):
        _install_auto_memory()


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore the stock ``benchmark`` fixture after the session."""
    _remove_auto_memory()
