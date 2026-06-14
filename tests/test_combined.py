from __future__ import annotations

from pytest_benchmem.combined import (
    _best_worst,
    _blob_of,
    _byte_unit,
    _mem_cell,
    _mem_columns,
    _MemCol,
    _rank_style,
    _rel,
)


def _bench(**stats):
    return stats  # bs.groups holds flat dicts; [prop] access is all the renderer needs


def test_best_worst_directions():
    benches = [
        _bench(
            min=1.0,
            max=5.0,
            mean=2.0,
            median=2.0,
            iqr=0.5,
            stddev=0.1,
            ops=10.0,
            outliers="0;0",
            rounds=3,
            iterations=1,
        ),
        _bench(
            min=3.0,
            max=9.0,
            mean=4.0,
            median=4.0,
            iqr=1.5,
            stddev=0.3,
            ops=4.0,
            outliers="1;2",
            rounds=7,
            iterations=1,
        ),
    ]
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


def test_byte_unit_picks_from_largest():
    assert _byte_unit(0) == ("B", 1.0)
    assert _byte_unit(2048)[0] == "KiB"
    assert _byte_unit(5 * 1024**2)[0] == "MiB"


def test_mem_columns_hoist_unit_and_rank():
    blobs = {
        "a": {"peak_bytes": 1024, "peak_bytes_max": 1024, "total_bytes": 2048, "allocations": 5},
        "b": {"peak_bytes": 8192, "peak_bytes_max": 8192, "total_bytes": 4096, "allocations": 50},
    }
    cols = _mem_columns(blobs)
    assert [c.header for c in cols] == ["peak (KiB)", "allocated (KiB)", "allocs"]  # no idle max
    assert cols[0].best == 1024 and cols[0].worst == 8192  # smaller is best


def test_mem_columns_includes_max_on_spread():
    blob = {"peak_bytes": 1024, "peak_bytes_max": 4096, "total_bytes": 0, "allocations": 0}
    assert any(c.header.startswith("max") for c in _mem_columns({"a": blob}))


def test_mem_cell_annotation_and_zero_floor():
    ranked = _MemCol("peak (KiB)", "peak_bytes", 1024.0, best=1024.0, worst=8192.0)
    assert "(8.00)" in _mem_cell(ranked, {"peak_bytes": 8192}, solo=False).plain
    zero_floor = _MemCol("peak (KiB)", "peak_bytes", 1024.0, best=0.0, worst=8192.0)
    assert "(" not in _mem_cell(zero_floor, {"peak_bytes": 8192}, solo=False).plain  # ratio dropped
    assert _mem_cell(ranked, None, solo=False).plain == "—"  # timing-only row


def test_blob_of_reads_flat_dict():
    blob = {"peak_bytes": 10, "mode": "heap"}
    assert _blob_of({"extra_info": {"benchmem": blob}}) == blob
    assert _blob_of({"extra_info": {}}) is None  # timing-only
    assert _blob_of({}) is None  # no extra_info key at all
    assert _blob_of({"extra_info": {"benchmem": "nope"}}) is None  # malformed
