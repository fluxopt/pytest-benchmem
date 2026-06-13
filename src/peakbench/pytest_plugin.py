"""pytest plugin — the ``benchmark_memory`` fixture, peakbench's reason to exist.

pytest-benchmark times your code but can't measure memory. This fixture adds a
memray peak-memory pass *to the same test, in the same run*, and stashes the
result in pytest-benchmark's own storage so timing and memory share one node id
and one JSON file::

    def test_build(benchmark_memory):
        benchmark_memory(build_model, 1000)
    # .benchmarks/.../NNNN.json, one entry:
    #   stats:      {min, mean, median, ...}   <- pytest-benchmark (timing)
    #   extra_info: {"peak_mib": 18.8}         <- peakbench (memory)

The two passes never overlap: pytest-benchmark times the action with no tracker
installed, then memray measures peak on a separate, untimed call. So the memray
allocator hooks — which would otherwise inflate timing severalfold — cost the
timing numbers nothing.

Timing rides pytest-benchmark's compare/histogram tooling natively. Memory comes
back out via :func:`peakbench.memory_from_pytest_benchmark` into peakbench's
unit-aware ``plot`` / ``compare``.

The fixture is registered via the ``pytest11`` entry point — installing peakbench
makes it available, no ``pytest_plugins`` wiring needed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

import pytest

from peakbench.memray import measure_peak

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture

#: Key under which the peak (MiB) is written into pytest-benchmark ``extra_info``.
PEAK_KEY = "peak_mib"


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
        = "sort"`` — and peakbench's readers pick them up as dims alongside the
        parametrize params. The peak is stored here too, under ``peak_mib``.
        """
        return self._benchmark.extra_info

    def __call__(self, function_to_benchmark: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Time ``function_to_benchmark(*args, **kwargs)``, then record its peak memory."""
        result = self._benchmark(function_to_benchmark, *args, **kwargs)
        self._record(lambda: function_to_benchmark(*args, **kwargs))
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

        def action() -> Any:
            call_args, call_kwargs = args, kwargs
            if setup is not None:
                produced = setup()
                if produced is not None:
                    call_args, call_kwargs = produced
            return target(*call_args, **call_kwargs)

        self._record(action)
        return result

    def _record(self, action: Callable[[], Any]) -> None:
        peak = measure_peak(action, repeats=self._repeats)
        self.peak_mib = peak
        self._benchmark.extra_info[PEAK_KEY] = peak


@pytest.fixture
def benchmark_memory(benchmark: BenchmarkFixture) -> MemoryBenchmark:
    """Time *and* peak-memory-profile a callable in one pytest-benchmark test.

    Depends on the ``benchmark`` fixture, so timing rides pytest-benchmark fully;
    the memray memory pass is added on top and stored in the same entry. Use the
    plain ``benchmark`` fixture instead for timing-only tests.
    """
    return MemoryBenchmark(benchmark)
