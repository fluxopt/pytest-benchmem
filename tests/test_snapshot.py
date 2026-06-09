from __future__ import annotations

import json

import pytest

from benchkit.snapshot import (
    Sample,
    from_pytest_benchmark,
    load_long_df,
    load_snapshot,
    write_snapshot,
)


def test_snapshot_roundtrip(tmp_path):
    samples = [Sample("build[n=10]", 18.8, {"op": "build", "n": 10})]
    p = write_snapshot(tmp_path / "m.json", "v1", samples, "MiB")
    label, loaded, unit = load_snapshot(p)
    assert label == "v1"
    assert unit == "MiB"
    assert loaded == samples


def test_load_long_df_has_dim_columns(tmp_path):
    write_snapshot(tmp_path / "a.json", "v1", [Sample("x", 1.0, {"op": "build", "n": 10})], "MiB")
    df, unit = load_long_df([tmp_path / "a.json"])
    assert unit == "MiB"
    assert {"snapshot", "id", "value", "op", "n"} <= set(df.columns)
    assert df.iloc[0]["n"] == 10


def test_mixed_units_raise(tmp_path):
    write_snapshot(tmp_path / "a.json", "v1", [Sample("x", 1.0, {})], "MiB")
    write_snapshot(tmp_path / "b.json", "v2", [Sample("x", 1.0, {})], "s")
    with pytest.raises(ValueError, match="mix units"):
        load_long_df([tmp_path / "a.json", tmp_path / "b.json"])


def test_from_pytest_benchmark(tmp_path):
    pb = tmp_path / "t.json"
    pb.write_text(json.dumps({"benchmarks": [{"fullname": "test_x[n=10]", "stats": {"min": 0.1}}]}))
    _label, samples, unit = from_pytest_benchmark(pb, dims_for=lambda _i: {"n": 10})
    assert unit == "s"
    assert samples[0].value == 0.1
    assert samples[0].dims == {"n": 10}


def test_malformed_snapshot_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    with pytest.raises(ValueError, match="not a readable JSON snapshot"):
        load_snapshot(bad)


def test_non_benchkit_snapshot_raises(tmp_path):
    f = tmp_path / "pb.json"
    f.write_text('{"benchmarks": []}')
    with pytest.raises(ValueError, match="not a benchkit snapshot"):
        load_snapshot(f)
