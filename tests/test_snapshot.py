from __future__ import annotations

import json
from pathlib import Path

import pytest

from pytest_benchmem.snapshot import (
    _node_dims,
    from_pytest_benchmark,
    human_bytes,
    load_long_df,
    load_samples,
    memory_from_pytest_benchmark,
)


@pytest.mark.parametrize(
    "n, expected",
    [
        (0, "0 B"),
        (512, "512 B"),
        (1024, "1 KiB"),
        (1536, "1.5 KiB"),
        (1024**2, "1 MiB"),
        (int(2.5 * 1024**3), "2.5 GiB"),
    ],
)
def test_human_bytes_scales(n, expected):
    assert human_bytes(n) == expected


def _pb_file(tmp_path, benchmarks):
    p = tmp_path / "0001_run.json"
    p.write_text(json.dumps({"benchmarks": benchmarks}))
    return p


def test_from_pytest_benchmark_reads_timing(tmp_path):
    pb = _pb_file(
        tmp_path,
        [{"fullname": "test_x[n=10]", "stats": {"min": 0.1, "mean": 0.2}, "params": {"n": 10}}],
    )
    label, samples, unit = from_pytest_benchmark(pb)
    assert (label, unit) == ("0001_run", "s")
    assert samples[0].value == 0.1
    assert samples[0].dims == {"n": 10}


def test_metric_picks_the_stat(tmp_path):
    pb = _pb_file(tmp_path, [{"fullname": "t", "stats": {"min": 0.1, "median": 0.3}}])
    _l, samples, _u = from_pytest_benchmark(pb, metric="median")
    assert samples[0].value == 0.3


def _blob(peak_bytes, *, allocations=0, total_bytes=0, repeats=1):
    return {
        "peak_bytes": peak_bytes,
        "peak_bytes_max": peak_bytes,
        "allocations": allocations,
        "total_bytes": total_bytes,
        "repeats": repeats,
    }


def test_dims_from_params_and_extra_info(tmp_path):
    pb = _pb_file(
        tmp_path,
        [
            {
                "fullname": "t[n=10]",
                "stats": {"min": 0.1},
                "params": {"n": 10},
                "extra_info": {"op": "sort", "benchmem": _blob(5_000_000)},  # blob excluded
            }
        ],
    )
    _l, samples, _u = from_pytest_benchmark(pb)
    assert samples[0].dims == {"n": 10, "op": "sort"}


def test_dims_drops_unserializable(tmp_path):
    # pytest-benchmark stamps a non-JSON param as "UNSERIALIZABLE[<repr>]"; it's a
    # broken axis (identical across objects), so it must not appear as a dim. The
    # literal prefix pins pytest-benchmark's format — a rename should fail here.
    pb = _pb_file(
        tmp_path,
        [
            {
                "fullname": "t[basic-n=10]",
                "stats": {"min": 0.1},
                "params": {"spec": "UNSERIALIZABLE[BenchSpec('basic')]", "n": 10},
                # also leaks via extra_info if the user stashes an object there
                "extra_info": {"cfg": "UNSERIALIZABLE[Config()]", "op": "sort"},
            }
        ],
    )
    _l, samples, _u = from_pytest_benchmark(pb)
    assert samples[0].dims == {"n": 10, "op": "sort"}


def test_node_dims_parses_module_func_class_group():
    assert _node_dims({"fullname": "pkg/test_m.py::TestC::test_run[a-n=10]", "group": "solve"}) == {
        "node.group": "solve",
        "node.module": "pkg/test_m.py",
        "node.func": "test_run",
        "node.class": "TestC",
    }


def test_node_dims_omits_what_it_cannot_determine():
    # plain function (no class), no group, params payload never parsed
    assert _node_dims({"fullname": "pkg/test_m.py::test_op[basic-n=10]"}) == {
        "node.module": "pkg/test_m.py",
        "node.func": "test_op",
    }
    # no "::" (doctest / odd id) -> fabricate nothing
    assert _node_dims({"fullname": "test_op[n=10]"}) == {}


def test_readers_add_node_dims_beside_params(tmp_path):
    pb = _pb_file(
        tmp_path,
        [{"fullname": "pkg/test_m.py::test_op[n=10]", "stats": {"min": 0.1}, "params": {"n": 10}}],
    )
    _l, samples, _u = from_pytest_benchmark(pb)
    assert samples[0].dims == {"n": 10, "node.module": "pkg/test_m.py", "node.func": "test_op"}


def test_user_dim_wins_over_node_dim(tmp_path):
    # the node. namespace makes a clash near-impossible; if one happens, the user wins
    pb = _pb_file(
        tmp_path,
        [
            {
                "fullname": "pkg/test_m.py::test_op",
                "stats": {"min": 0.1},
                "extra_info": {"node.func": "custom"},
            }
        ],
    )
    _l, samples, _u = from_pytest_benchmark(pb)
    assert samples[0].dims["node.func"] == "custom"


def test_dims_drops_non_scalar_values(tmp_path):
    # Lists/dicts are unhashable — they'd break pandas groupby on faceting, so a
    # non-scalar param/extra_info value is not a usable axis and must be dropped.
    pb = _pb_file(
        tmp_path,
        [
            {
                "fullname": "t[n=10]",
                "stats": {"min": 0.1},
                "params": {"sizes": [10, 250], "n": 10},
                "extra_info": {"meta": {"k": "v"}, "op": "sort"},
            }
        ],
    )
    _l, samples, _u = from_pytest_benchmark(pb)
    assert samples[0].dims == {"n": 10, "op": "sort"}


def test_memory_from_pytest_benchmark_reads_blob(tmp_path):
    pb = _pb_file(
        tmp_path,
        [
            {"fullname": "a", "stats": {"min": 0.1}, "extra_info": {"benchmem": _blob(19_700_000)}},
            {"fullname": "b", "stats": {"min": 0.2}},  # timing-only — skipped
            {"fullname": "c", "stats": {"min": 0.3}, "extra_info": {"benchmem": None}},  # skipped
        ],
    )
    _l, samples, unit = memory_from_pytest_benchmark(pb)
    assert unit == "B"
    assert [(s.id, s.value) for s in samples] == [("a", 19_700_000.0)]


def test_metric_memory_is_alias_for_peak(tmp_path):
    pb = _pb_file(
        tmp_path,
        [{"fullname": "a", "stats": {"min": 0.1}, "extra_info": {"benchmem": _blob(19_700_000)}}],
    )
    _l, peak, unit_peak = load_samples(pb, metric="peak")
    _l, mem, unit_mem = load_samples(pb, metric="memory")
    assert unit_mem == unit_peak == "B"
    assert [s.value for s in mem] == [s.value for s in peak] == [19_700_000.0]


def test_memory_reads_allocations_field(tmp_path):
    pb = _pb_file(
        tmp_path,
        [
            {
                "fullname": "a",
                "stats": {"min": 0.1},
                "extra_info": {"benchmem": _blob(99, allocations=42)},
            }
        ],
    )
    _l, samples, unit = memory_from_pytest_benchmark(pb, field="allocations")
    assert unit == ""
    assert samples[0].value == 42.0


def test_load_samples_dispatches_on_metric(tmp_path):
    pb = _pb_file(
        tmp_path,
        [
            {
                "fullname": "a",
                "stats": {"min": 0.1},
                "extra_info": {"benchmem": _blob(5_000, allocations=7, total_bytes=20_000)},
            }
        ],
    )
    assert load_samples(pb, metric="time")[2] == "s"
    assert load_samples(pb, metric="peak")[1][0].value == 5_000
    assert load_samples(pb, metric="allocated")[1][0].value == 20_000
    assert load_samples(pb, metric="allocations")[1][0].value == 7
    assert load_samples(pb, metric="allocated")[2] == "B"
    assert load_samples(pb, metric="allocations")[2] == ""


def _mode_blob(mode, **fields):
    return {"peak_bytes": 100, "peak_bytes_max": 150, "repeats": 1, "mode": mode, **fields}


def _blob_file(path, blob):
    bm = {"fullname": "a", "stats": {"min": 0.1}, "extra_info": {"benchmem": blob}}
    path.write_text(json.dumps({"benchmarks": [bm]}))
    return path


def test_peak_max_metric_reads_worst_peak(tmp_path):
    # peak_max is shared across modes; reads the max-of-repeats peak
    for mode in ("heap", "rss"):
        pb = _blob_file(tmp_path / f"{mode}.json", _mode_blob(mode))
        _l, samples, unit = load_samples(pb, metric="peak_max")
        assert (samples[0].value, unit) == (150.0, "B")


def test_gross_metric_is_rss_only(tmp_path):
    rss = _blob_file(tmp_path / "rss.json", _mode_blob("rss", gross_bytes=5_000))
    assert load_samples(rss, metric="gross")[1][0].value == 5_000

    heap = _blob_file(tmp_path / "heap.json", _mode_blob("heap"))
    with pytest.raises(ValueError, match="'gross' is rss-only.*measured in 'heap'"):
        load_samples(heap, metric="gross")


def test_heap_only_metric_on_rss_run_errors_not_skips(tmp_path):
    # the silent-skip fix: asking allocated on an rss run is an error, not an empty result
    rss = _blob_file(tmp_path / "rss.json", _mode_blob("rss", gross_bytes=9))
    with pytest.raises(ValueError, match="'allocated' is heap-only.*Pick a rss metric"):
        load_samples(rss, metric="allocated")


def test_load_long_df_stacks_runs_with_dim_columns(tmp_path):
    a = tmp_path / "v1.json"
    b = tmp_path / "v2.json"
    a.write_text(
        json.dumps({"benchmarks": [{"fullname": "x", "stats": {"min": 1.0}, "params": {"n": 10}}]})
    )
    b.write_text(
        json.dumps({"benchmarks": [{"fullname": "x", "stats": {"min": 2.0}, "params": {"n": 10}}]})
    )
    df, unit = load_long_df([a, b], metric="time")
    assert unit == "s"
    assert set(df["snapshot"]) == {"v1", "v2"}
    assert {"snapshot", "id", "value", "n"} <= set(df.columns)


def test_load_long_df_accepts_single_path(tmp_path):
    # a bare str/Path is one file, not a sequence of characters
    pb = _pb_file(tmp_path, [{"fullname": "x", "stats": {"min": 1.0}, "params": {"n": 10}}])
    from_str, _ = load_long_df(str(pb))
    from_path, _ = load_long_df(pb)
    assert len(from_str) == len(from_path) == 1


def test_load_long_df_labels_override_stem(tmp_path):
    a, b = tmp_path / "run-a.json", tmp_path / "run-b.json"
    for p in (a, b):
        p.write_text(json.dumps({"benchmarks": [{"fullname": "x", "stats": {"min": 1.0}}]}))
    df, _u = load_long_df([a, b], labels=["v1", "v2"])
    assert set(df["snapshot"]) == {"v1", "v2"}  # not the run-a / run-b stems
    with pytest.raises(ValueError, match="labels has 1 entries but there are 2"):
        load_long_df([a, b], labels=["only-one"])


def test_default_labels_disambiguate_colliding_stems():
    from pytest_benchmem.snapshot import _default_labels

    # distinct stems pass through; a shared stem is disambiguated by parent dir
    assert _default_labels([Path("a/v1.json"), Path("b/v2.json")]) == ["v1", "v2"]
    assert _default_labels([Path("v1/bench.json"), Path("v2/bench.json")]) == [
        "v1/bench",
        "v2/bench",
    ]


def test_memory_mode_defaults_to_heap_for_older_blobs(tmp_path):
    # a blob predating the mode tag reads as the heap default.
    pb = _pb_file(
        tmp_path,
        [{"fullname": "a", "stats": {"min": 0.1}, "extra_info": {"benchmem": _blob(99)}}],
    )
    _l, samples, _u = memory_from_pytest_benchmark(pb)
    assert samples[0].dims["mode"] == "heap"


def test_memory_mode_read_from_blob(tmp_path):
    blob = {**_blob(99), "mode": "rss"}
    pb = _pb_file(
        tmp_path,
        [{"fullname": "a", "stats": {"min": 0.1}, "extra_info": {"benchmem": blob}}],
    )
    _l, samples, _u = memory_from_pytest_benchmark(pb)
    assert samples[0].dims["mode"] == "rss"


def _mode_file(tmp_path, name, mode):
    extra = {"benchmem": {**_blob(99), "mode": mode}}
    bm = {"fullname": "x", "stats": {"min": 0.1}, "extra_info": extra}
    p = tmp_path / name
    p.write_text(json.dumps({"benchmarks": [bm]}))
    return p


def test_load_long_df_refuses_mixed_modes(tmp_path):
    heap = _mode_file(tmp_path, "heap.json", "heap")
    rss = _mode_file(tmp_path, "rss.json", "rss")
    with pytest.raises(ValueError, match="mix memory modes"):
        load_long_df([heap, rss], metric="peak")


def test_load_long_df_allows_single_mode(tmp_path):
    files = [_mode_file(tmp_path, "a.json", "heap"), _mode_file(tmp_path, "b.json", "heap")]
    df, unit = load_long_df(files, metric="peak")
    assert unit == "B"
    assert set(df["mode"]) == {"heap"}


def test_not_a_pytest_benchmark_file_raises(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text('{"nope": []}')
    with pytest.raises(ValueError, match="not a pytest-benchmark file"):
        from_pytest_benchmark(f)


def test_unreadable_json_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    with pytest.raises(ValueError, match="not a readable JSON file"):
        from_pytest_benchmark(bad)
