from __future__ import annotations

from pytest_benchmem.combined import _best_worst, _peak_delta_cells, _rank_style, _rel, _result_of
from pytest_benchmem.memray import Measurement, MemoryResult


def _bench(**stats):
    return stats  # bs.groups holds flat dicts; [prop] access is all the renderer needs


def test_best_worst_directions():
    benches = [
        _bench(min=1.0, max=5.0, mean=2.0, median=2.0, iqr=0.5, stddev=0.1, ops=10.0,
               outliers="0;0", rounds=3, iterations=1),
        _bench(min=3.0, max=9.0, mean=4.0, median=4.0, iqr=1.5, stddev=0.3, ops=4.0,
               outliers="1;2", rounds=7, iterations=1),
    ]  # fmt: skip
    best, worst = _best_worst(benches)
    assert best["min"] == 1.0 and worst["min"] == 3.0  # time: smaller is better
    assert best["ops"] == 10.0 and worst["ops"] == 4.0  # ops: bigger is better
    assert worst["rounds"] == 7  # counts only get a worst


def test_rank_style_colours_extremes_only():
    assert _rank_style(1.0, best=1.0, worst=5.0, solo=False) == "green"
    assert _rank_style(5.0, best=1.0, worst=5.0, solo=False) == "red"
    assert _rank_style(3.0, best=1.0, worst=5.0, solo=False) is None
    assert _rank_style(1.0, best=1.0, worst=5.0, solo=True) is None  # nothing to contrast


def test_rel_matches_pytest_benchmark_annotation():
    assert _rel(5.0, 5.0, solo=False) == " (1.0)"  # the group best
    assert _rel(10.0, 5.0, solo=False) == " (2.00)"  # 2x the best
    assert _rel(50_000.0, 1.0, solo=False) == " (>1000.0)"  # pytest-benchmark's cutoff
    assert _rel(0.02, 10.0, solo=False) == " (0.00)"  # ops ratio below best
    assert _rel(10.0, 5.0, solo=True) == ""  # dropped for a solo group


def test_result_of_reconstructs_or_none():
    blob = {"peak_bytes": [10, 20], "allocations": [1, 1], "total_bytes": [5, 5]}
    res = _result_of({"extra_info": {"benchmem": blob}})
    assert res is not None and res.peak_bytes == 10 and res.peak_bytes_max == 20
    assert _result_of({"extra_info": {}}) is None  # timing-only
    assert _result_of({}) is None  # no extra_info at all
    assert _result_of({"extra_info": {"benchmem": "nope"}}) is None  # malformed


def test_peak_delta_cells_fold_baseline():
    base = MemoryResult((Measurement(4096, 1, 1),))
    res = MemoryResult((Measurement(8192, 1, 1),))
    cells = _peak_delta_cells(base, res, 1024.0)  # KiB factor
    assert cells[0].plain == "4.00" and cells[1].plain == "+100.0%"  # baseline in peak's unit; grew
    absent = _peak_delta_cells(None, res, 1024.0)
    assert absent[0].plain == "—" and absent[1].plain == "—"  # id not in baseline
