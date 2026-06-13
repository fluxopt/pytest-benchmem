from __future__ import annotations

import json

import pytest

from pytest_benchmem.snapshot import (
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


def _blob(peak_bytes, *, allocations=0, repeats=1):
    return {
        "peak_bytes": peak_bytes,
        "peak_bytes_max": peak_bytes,
        "allocations": allocations,
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
        [{"fullname": "a", "stats": {"min": 0.1}, "extra_info": {"benchmem": _blob(5_000)}}],
    )
    assert load_samples(pb, metric="time")[2] == "s"
    assert load_samples(pb, metric="memory")[2] == "B"


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
