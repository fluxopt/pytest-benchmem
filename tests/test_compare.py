from __future__ import annotations

import json
from io import StringIO

import pytest

pytest.importorskip("pandas")

from pytest_benchmem.compare import (
    compare_runs,
    find_regressions,
    parse_threshold,
)


def _write(path, benchmarks):
    path.write_text(json.dumps({"benchmarks": benchmarks}))
    return path


def _bm(name, *, t=0.0, peak=None, allocations=0, total_bytes=0):
    bm = {"fullname": name, "stats": {"min": t}}
    if peak is not None:
        bm["extra_info"] = {
            "benchmem": {
                "peak_bytes": peak,
                "peak_bytes_max": peak,
                "allocations": allocations,
                "total_bytes": total_bytes,
                "repeats": 1,
            }
        }
    return bm


def _line(text, needle):
    return next(line for line in text.splitlines() if needle in line)


def test_same_file_twice_errors_cleanly(tmp_path):
    # identical labels used to crash with IndexError on labels[0], labels[1] (#62)
    a = _write(tmp_path / "run.json", [_bm("test_x", t=1.0)])
    with pytest.raises(ValueError, match="two distinct runs"):
        compare_runs([a, a], out=StringIO())


def test_distinct_files_same_stem_disambiguate(tmp_path):
    # two real runs that happen to share a stem (v1/bench.json vs v2/bench.json)
    # is a legit comparison and must not collapse to one series.
    (tmp_path / "v1").mkdir()
    (tmp_path / "v2").mkdir()
    a = _write(tmp_path / "v1" / "bench.json", [_bm("test_x", t=1.0)])
    b = _write(tmp_path / "v2" / "bench.json", [_bm("test_x", t=2.0)])
    out = StringIO()
    compare_runs([a, b], out=out)
    assert "v1/bench" in out.getvalue() and "v2/bench" in out.getvalue()


def test_percent_change_time(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("test_x", t=1.0), _bm("test_y", t=2.0)])
    b = _write(tmp_path / "head.json", [_bm("test_x", t=1.5), _bm("test_y", t=1.0)])
    out = StringIO()
    compare_runs([a, b], out=out)  # metric defaults to "time"
    text = out.getvalue()
    assert "(s)" in text  # unit in the header
    assert "+50.0%" in _line(text, "test_x")  # 1.0 -> 1.5
    assert "-50.0%" in _line(text, "test_y")  # 2.0 -> 1.0


def test_memory_metric_reads_blob(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("test_x", peak=10 * 1024**2)])
    b = _write(tmp_path / "head.json", [_bm("test_x", peak=12 * 1024**2)])
    out = StringIO()
    compare_runs([a, b], metric="peak", out=out)
    text = out.getvalue()
    assert "peak (MiB)" in text  # unit hoisted into the header, one scale for the table
    assert "10.00" in text and "12.00" in text  # cells are bare numbers in that unit
    assert "+20.0%" in _line(text, "test_x")  # 10 MiB -> 12 MiB


def test_one_sided_ids_show_dash(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("only_a", t=1.0)])
    b = _write(tmp_path / "head.json", [_bm("only_b", t=2.0)])
    out = StringIO()
    compare_runs([a, b], out=out)
    text = out.getvalue()
    # each id is in only one run → the missing value column AND the change show —
    assert _line(text, "only_a").count("—") == 2
    assert _line(text, "only_b").count("—") == 2


def test_zero_baseline_suppresses_percent(tmp_path):
    # change is guarded by `va > 0`, so a 0 baseline can't divide-by-zero
    a = _write(tmp_path / "base.json", [_bm("test_x", t=0.0)])
    b = _write(tmp_path / "head.json", [_bm("test_x", t=1.0)])
    out = StringIO()
    compare_runs([a, b], out=out)
    assert _line(out.getvalue(), "test_x").rstrip().endswith("—")


def _bm_series(name, peaks):
    """A benchmark blob carrying a per-repeat peak series (allocations/total constant)."""
    return {
        "fullname": name,
        "stats": {"min": 1.0},
        "extra_info": {
            "benchmem": {
                "peak_bytes": min(peaks),
                "peak_bytes_max": max(peaks),
                "allocations": 1,
                "total_bytes": 1,
                "repeats": len(peaks),
                "series": {
                    "peak_bytes": peaks,
                    "allocations": [1] * len(peaks),
                    "total_bytes": [1] * len(peaks),
                },
            }
        },
    }


def test_compare_stat_reports_distribution(tmp_path):
    a = _write(tmp_path / "a.json", [_bm_series("test_x", [10, 20, 30])])
    b = _write(tmp_path / "b.json", [_bm_series("test_x", [40, 50, 60])])
    out = StringIO()
    compare_runs([a, b], metric="peak", stat="mean", out=out)
    text = out.getvalue()
    assert "peak mean" in text  # heading names the stat
    assert "20" in _line(text, "test_x") and "50" in _line(text, "test_x")  # mean of each series


def test_three_runs_render_one_table_no_change_column(tmp_path):
    # a cross-version sweep is just N runs → one column each, no two-run change column
    a = _write(tmp_path / "v1.json", [_bm("test_x", peak=1 * 1024**2)])
    b = _write(tmp_path / "v2.json", [_bm("test_x", peak=2 * 1024**2)])
    c = _write(tmp_path / "v3.json", [_bm("test_x", peak=4 * 1024**2)])
    out = StringIO()
    compare_runs([a, b, c], metric="peak", out=out)
    text = out.getvalue()
    assert "v1" in text and "v2" in text and "v3" in text  # one column per run
    assert "change" not in text  # the delta column is only for exactly two runs


# --- the regression gate (--fail-on) ---------------------------------------------


def test_parse_threshold_percent_and_absolute():
    pct = parse_threshold("peak:10%")
    assert (pct.field, pct.limit, pct.is_pct) == ("peak", 10.0, True)
    absolute = parse_threshold("peak:5MiB")
    assert (absolute.field, absolute.is_pct) == ("peak", False)
    assert absolute.limit == 5 * 1024**2
    assert parse_threshold("time:1ms").limit == pytest.approx(1e-3)
    assert parse_threshold("allocations:100").limit == 100.0


@pytest.mark.parametrize(
    "expr, needle",
    [
        ("peak", "expected FIELD:THRESHOLD"),
        ("bogus:5%", "unknown field"),
        ("allocations:5MiB", "is a count"),
        ("peak:5PiB", "unknown unit"),
        ("peak:abc", "not a number"),
    ],
)
def test_parse_threshold_rejects_bad_input(expr, needle):
    with pytest.raises(ValueError, match=needle):
        parse_threshold(expr)


def test_find_regressions_percent(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("x", peak=100), _bm("y", peak=100)])
    b = _write(tmp_path / "head.json", [_bm("x", peak=120), _bm("y", peak=105)])
    regs = find_regressions(a, b, [parse_threshold("peak:10%")])
    # only x grew >10% (20%); y grew 5% → under threshold
    assert [(r.id, round(r.pct, 1)) for r in regs] == [("x", 20.0)]


def test_find_regressions_absolute_bytes(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("x", peak=1024**2)])
    b = _write(tmp_path / "head.json", [_bm("x", peak=1024**2 + 2 * 1024**2)])  # +2 MiB
    assert find_regressions(a, b, [parse_threshold("peak:1MiB")])  # grew 2 MiB > 1 MiB
    assert not find_regressions(a, b, [parse_threshold("peak:3MiB")])  # under 3 MiB


def test_find_regressions_allocations(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("x", peak=10, allocations=100)])
    b = _write(tmp_path / "head.json", [_bm("x", peak=10, allocations=130)])
    assert find_regressions(a, b, [parse_threshold("allocations:20%")])  # +30%
    assert not find_regressions(a, b, [parse_threshold("allocations:50%")])


def test_find_regressions_allocated_total_bytes(tmp_path):
    # peak flat, but total churn doubled — caught by the 'allocated' gate
    a = _write(tmp_path / "base.json", [_bm("x", peak=10, total_bytes=1_000_000)])
    b = _write(tmp_path / "head.json", [_bm("x", peak=10, total_bytes=2_000_000)])
    assert find_regressions(a, b, [parse_threshold("allocated:50%")])
    assert find_regressions(a, b, [parse_threshold("allocated:0.5MiB")])  # grew ~1 MiB
    assert not find_regressions(a, b, [parse_threshold("peak:1%")])  # peak unchanged


def test_find_regressions_ignores_improvements(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("x", peak=200)])
    b = _write(tmp_path / "head.json", [_bm("x", peak=100)])  # halved — not a regression
    assert find_regressions(a, b, [parse_threshold("peak:1%")]) == []
