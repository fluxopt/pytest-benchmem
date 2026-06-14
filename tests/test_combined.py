from __future__ import annotations

from pytest_benchmem.combined import _best_worst, _blob_of, _rank_style


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


def test_blob_of_reads_flat_dict():
    blob = {"peak_bytes": 10, "mode": "heap"}
    assert _blob_of({"extra_info": {"benchmem": blob}}) == blob
    assert _blob_of({"extra_info": {}}) is None  # timing-only
    assert _blob_of({}) is None  # no extra_info key at all
    assert _blob_of({"extra_info": {"benchmem": "nope"}}) is None  # malformed
