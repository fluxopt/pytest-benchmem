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
                "peak_bytes": [peak],
                "allocations": [allocations],
                "total_bytes": [total_bytes],
            }
        }
    return bm


def _line(text, needle):
    return next(line for line in text.splitlines() if needle in line)


def _lines(text, needle):
    """All lines mentioning ``needle`` (a benchmark spans a heading + one row per run)."""
    return "\n".join(line for line in text.splitlines() if needle in line)


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


def test_time_column_shows_relative_multiplier(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("test_x", t=1.0), _bm("test_y", t=2.0)])
    b = _write(tmp_path / "head.json", [_bm("test_x", t=1.5), _bm("test_y", t=1.0)])
    out = StringIO()
    compare_runs([a, b], out=out)  # metric defaults to "time"
    text = out.getvalue()
    assert "time (s)" in text  # unit hoisted into the column header
    assert "(1.50)" in _lines(text, "test_x")  # head 1.5 is 1.50× the best run (1.0)
    assert "(2.00)" in _lines(text, "test_y")  # base 2.0 is 2.00× the best run (1.0)


def test_metric_both_shows_time_and_peak_columns(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("test_x", t=1.0, peak=10 * 1024**2)])
    b = _write(tmp_path / "head.json", [_bm("test_x", t=1.0, peak=12 * 1024**2)])
    out = StringIO()
    compare_runs([a, b], metric="both", out=out)
    text = out.getvalue()
    assert "time (s)" in text and "peak (MiB)" in text  # both metric columns, each its unit
    assert "(1.20)" in _lines(text, "test_x")  # peak 12 MiB is 1.20× the best run (10)


def test_columns_overrides_metric(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("test_x", t=1.0, peak=1024, allocations=5)])
    b = _write(tmp_path / "head.json", [_bm("test_x", t=1.0, peak=1024, allocations=9)])
    out = StringIO()
    compare_runs([a, b], columns="peak,allocations", out=out)
    text = out.getvalue()
    assert "peak (" in text and "allocations" in text and "time" not in text


def test_unknown_column_metric_raises(tmp_path):
    a = _write(tmp_path / "a.json", [_bm("x", t=1.0)])
    b = _write(tmp_path / "b.json", [_bm("x", t=2.0)])
    with pytest.raises(ValueError, match="unknown column metric"):
        compare_runs([a, b], columns="time,bogus", out=StringIO())


def test_group_by_func_clusters_variants(tmp_path):
    bms_a = [_bm("pkg::test_op[n=1]", t=1.0), _bm("pkg::test_op[n=2]", t=2.0)]
    bms_b = [_bm("pkg::test_op[n=1]", t=1.0), _bm("pkg::test_op[n=2]", t=2.0)]
    a, b = _write(tmp_path / "a.json", bms_a), _write(tmp_path / "b.json", bms_b)
    out = StringIO()
    compare_runs([a, b], group_by="func", out=out)
    text = out.getvalue()
    # one sub-table for the func, both n-variants (× both runs) under it
    assert text.count("benchmark 'test_op'") == 1
    assert "test_op[n=1]" in text and "test_op[n=2]" in text


def test_unknown_group_by_key_raises(tmp_path):
    a = _write(tmp_path / "a.json", [_bm("x", t=1.0)])
    b = _write(tmp_path / "b.json", [_bm("x", t=2.0)])
    with pytest.raises(ValueError, match="unknown --group-by key"):
        compare_runs([a, b], group_by="bogus", out=StringIO())


def test_missing_metric_cell_shows_dash(tmp_path):
    # test_x has time in both runs but memory only in run b → its run-a peak cell is —
    a = _write(tmp_path / "a.json", [_bm("test_x", t=1.0)])
    b = _write(tmp_path / "b.json", [_bm("test_x", t=1.0, peak=1024)])
    out = StringIO()
    compare_runs([a, b], columns="time,peak", out=out)
    assert "—" in _lines(out.getvalue(), "test_x")


def test_one_sided_id_shows_only_its_run(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("only_a", t=1.0)])
    b = _write(tmp_path / "head.json", [_bm("only_b", t=2.0)])
    out = StringIO()
    compare_runs([a, b], out=out)
    text = out.getvalue()
    assert "only_a (base)" in text and "only_b (head)" in text  # the run each was seen in
    assert "only_a (head)" not in text  # absent run → no row, not a dash


def test_csv_writes_raw_values_per_metric_run(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("test_x", peak=10 * 1024**2)])
    b = _write(tmp_path / "head.json", [_bm("test_x", peak=12 * 1024**2)])
    csv = tmp_path / "out.csv"
    compare_runs([a, b], metric="peak", csv=csv, out=StringIO())
    text = csv.read_text()
    assert "peak:base" in text and "peak:head" in text  # one column per metric:run
    assert "10485760" in text and "12582912" in text  # raw bytes, not unit-scaled


def test_sort_value_orders_rows_in_a_single_table(tmp_path):
    a = _write(tmp_path / "a.json", [_bm("small", peak=1024), _bm("big", peak=10 * 1024**2)])
    b = _write(tmp_path / "b.json", [_bm("small", peak=1024), _bm("big", peak=10 * 1024**2)])
    body = StringIO()
    compare_runs([a, b], metric="peak", group_by=None, sort="value", out=body)
    text = body.getvalue()
    assert text.index("big") < text.index("small")  # largest in the last run first


def test_sort_rejects_unknown_key(tmp_path):
    a = _write(tmp_path / "a.json", [_bm("x", peak=1)])
    b = _write(tmp_path / "b.json", [_bm("x", peak=2)])
    with pytest.raises(ValueError, match="unknown --sort"):
        compare_runs([a, b], metric="peak", sort="bogus", out=StringIO())


def test_zero_value_suppresses_multiplier(tmp_path):
    # the group best is 0 → no meaningful ratio, so no (N.NN) annotation (no divide-by-zero)
    a = _write(tmp_path / "base.json", [_bm("test_x", t=0.0)])
    b = _write(tmp_path / "head.json", [_bm("test_x", t=1.0)])
    out = StringIO()
    compare_runs([a, b], out=out)
    rows = _lines(out.getvalue(), "test_x")
    assert "(1.0)" not in rows and "(inf)" not in rows  # only the "(base)/(head)" parens remain


def _bm_series(name, peaks):
    """A benchmark blob carrying a per-repeat peak series (allocations/total constant)."""
    return {
        "fullname": name,
        "stats": {"min": 1.0},
        "extra_info": {
            "benchmem": {
                "peak_bytes": peaks,
                "allocations": [1] * len(peaks),
                "total_bytes": [1] * len(peaks),
            }
        },
    }


def test_compare_stat_reports_distribution(tmp_path):
    a = _write(tmp_path / "a.json", [_bm_series("test_x", [10, 20, 30])])
    b = _write(tmp_path / "b.json", [_bm_series("test_x", [40, 50, 60])])
    out = StringIO()
    compare_runs([a, b], metric="peak", stat="mean", out=out)
    rows = _lines(out.getvalue(), "test_x")
    assert "20" in rows and "50" in rows  # the per-run mean of each series


def test_three_runs_stack_as_rows_with_multipliers(tmp_path):
    # a cross-version sweep is N runs → one row per run, relative to the best run
    a = _write(tmp_path / "v1.json", [_bm("test_x", peak=1 * 1024**2)])
    b = _write(tmp_path / "v2.json", [_bm("test_x", peak=2 * 1024**2)])
    c = _write(tmp_path / "v3.json", [_bm("test_x", peak=4 * 1024**2)])
    out = StringIO()
    compare_runs([a, b, c], metric="peak", out=out)
    text = out.getvalue()
    assert "(v1)" in text and "(v2)" in text and "(v3)" in text  # one row per run
    assert "(2.00)" in text and "(4.00)" in text  # vs the best run (v1)
    assert "change" not in text  # no delta column in the relative-multiplier model


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
