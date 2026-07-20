from __future__ import annotations

import json
from io import StringIO

import pytest

pytest.importorskip("pandas")

from pytest_benchmem.compare import (
    compare_runs,
    find_pivot_regressions,
    find_regressions,
    parse_threshold,
)


def _write(path, benchmarks):
    path.write_text(json.dumps({"benchmarks": benchmarks}))
    return path


def _bm(name, *, t=0.0, peak=None, allocations=0, total_bytes=0, rss=None):
    # real pytest-benchmark files carry every stat; mirror that so --stat all can read them
    bm = {"fullname": name, "stats": {s: t for s in ("min", "max", "mean", "median", "stddev")}}
    if peak is not None:
        blob = {
            "peak_bytes": [peak],
            "allocations": [allocations],
            "total_bytes": [total_bytes],
        }
        if rss is not None:  # an isolated run also carries rss_bytes
            blob["rss_bytes"] = [rss]
        bm["extra_info"] = {"benchmem": blob}
    return bm


def _lines(text, needle):
    """The block for ``needle``'s benchmark: its bold header line plus the rows under it.

    A benchmark renders as a header line (the group id, at column 0) followed by its
    run rows (indented) — so capture the header carrying ``needle`` and everything until
    the next header (rows and the box rule never start with an alphanumeric).
    """
    block, capturing = [], False
    for line in text.splitlines():
        if line[:1].isalnum():  # a new group header
            capturing = needle in line
        if capturing:
            block.append(line)
    return "\n".join(block)


def test_same_file_twice_errors_cleanly(tmp_path):
    # identical labels used to crash with IndexError on labels[0], labels[1] (#62)
    a = _write(tmp_path / "run.json", [_bm("test_x", t=1.0)])
    with pytest.raises(ValueError, match="two distinct runs"):
        compare_runs([a, a], out=StringIO())


def test_single_run_prints_plain_table(tmp_path):
    # one run is a valid input: a plain readout, no cross-run multiplier or ranking colour
    a = _write(tmp_path / "run.json", [_bm("test_x", t=1.0, peak=10 * 1024**2)])
    out = StringIO()
    compare_runs([a], columns="time,peak", out=out)
    text = out.getvalue()
    assert "time (s)" in text and "peak (MiB)" in text  # the columns still render
    rows = _lines(text, "test_x")
    assert "(run)" in rows  # the single run's label still names the row
    assert "(1.0)" not in rows  # nothing to compare against → no relative multiplier


def test_single_run_multi_id_has_no_within_run_ranking(tmp_path):
    # a single run with several ids in one group is still plain — no (N.NN) ranking the
    # ids against each other (that's reserved for the cross-run comparison).
    a = _write(
        tmp_path / "run.json",
        [_bm("pkg::test_op[n=1]", peak=1024), _bm("pkg::test_op[n=2]", peak=10 * 1024**2)],
    )
    out = StringIO()
    compare_runs([a], columns="peak", group_by="func", out=out)
    text = out.getvalue()
    assert "test_op[n=1]" in text and "test_op[n=2]" in text
    assert "(1.0)" not in text and "(10240.00)" not in text  # no within-run multiplier


def test_single_run_empty_file_errors(tmp_path):
    a = _write(tmp_path / "run.json", [])
    with pytest.raises(ValueError, match="no benchmarks"):
        compare_runs([a], out=StringIO())


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
    compare_runs([a, b], out=out)  # columns default to all; only time has data here
    text = out.getvalue()
    assert "time (s)" in text  # unit hoisted into the column header
    assert "(1.50)" in _lines(text, "test_x")  # head 1.5 is 1.50× the best run (1.0)
    assert "(2.00)" in _lines(text, "test_y")  # base 2.0 is 2.00× the best run (1.0)


def test_metric_both_shows_time_and_peak_columns(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("test_x", t=1.0, peak=10 * 1024**2)])
    b = _write(tmp_path / "head.json", [_bm("test_x", t=1.0, peak=12 * 1024**2)])
    out = StringIO()
    compare_runs([a, b], columns="time,peak", out=out)
    text = out.getvalue()
    assert "time (s)" in text and "peak (MiB)" in text  # both metric columns, each its unit
    assert "(1.20)" in _lines(text, "test_x")  # peak 12 MiB is 1.20× the best run (10)


def test_columns_selects_specific_metrics(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("test_x", t=1.0, peak=1024, allocations=5)])
    b = _write(tmp_path / "head.json", [_bm("test_x", t=1.0, peak=1024, allocations=9)])
    out = StringIO()
    compare_runs([a, b], columns="peak,allocations", out=out)
    text = out.getvalue()
    assert "peak (" in text and "allocations" in text and "time" not in text


def test_divider_marks_timed_untimed_boundary(tmp_path):
    # time (pytest-benchmark's timed rounds) | peak (the separate untimed memray pass)
    a = _write(tmp_path / "a.json", [_bm("test_x", t=1.0, peak=10 * 1024**2)])
    b = _write(tmp_path / "b.json", [_bm("test_x", t=1.0, peak=12 * 1024**2)])
    out = StringIO()
    compare_runs([a, b], columns="time,peak", stat="min", out=out)
    assert "│" in out.getvalue()


def test_no_divider_among_memory_metrics(tmp_path):
    # peak and allocated both come from the untimed pass → no provenance boundary between them
    a = _write(tmp_path / "a.json", [_bm("test_x", peak=10 * 1024**2, total_bytes=10 * 1024**2)])
    b = _write(tmp_path / "b.json", [_bm("test_x", peak=12 * 1024**2, total_bytes=12 * 1024**2)])
    out = StringIO()
    compare_runs([a, b], columns="peak,allocated", stat="min", out=out)
    assert "│" not in out.getvalue()


def test_default_is_time_and_peak_across_every_stat(tmp_path):
    # no --columns/--stat → the two headline metrics, each across the full stat spread;
    # allocated/allocations stay opt-in
    a = _write(tmp_path / "a.json", [_bm("test_x", t=1.0, peak=2048, allocations=5, total_bytes=8)])
    b = _write(tmp_path / "b.json", [_bm("test_x", t=1.0, peak=4096, allocations=7, total_bytes=9)])
    out = StringIO()
    compare_runs([a, b], out=out)
    text = out.getvalue()
    assert "time (s)" in text and "peak (" in text  # the two headline metrics
    assert "allocated" not in text and "allocations" not in text  # opt-in only
    assert all(s in text for s in ("min", "max", "mean", "median", "stddev"))  # full spread


def test_default_drops_columns_absent_from_every_run(tmp_path):
    # timing-only runs → the memory columns have no data and are dropped, not shown all-dash
    a = _write(tmp_path / "a.json", [_bm("test_x", t=1.0)])
    b = _write(tmp_path / "b.json", [_bm("test_x", t=2.0)])
    out = StringIO()
    compare_runs([a, b], out=out)
    text = out.getvalue()
    assert "time (s)" in text
    assert "peak" not in text and "alloc" not in text


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
    # one sub-table for the func (its bare header line), both n-variants (× both runs) under it
    assert text.splitlines().count("test_op") == 1
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
    # each id heads its own single-id sub-table; the row under it is just the run it was seen in
    assert "(base)" in _lines(text, "only_a") and "(head)" in _lines(text, "only_b")
    assert "(head)" not in _lines(text, "only_a")  # absent run → no row, not a dash


def test_csv_writes_raw_values_per_metric_run(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("test_x", peak=10 * 1024**2)])
    b = _write(tmp_path / "head.json", [_bm("test_x", peak=12 * 1024**2)])
    csv = tmp_path / "out.csv"
    compare_runs([a, b], columns="peak", stat="min", csv=csv, out=StringIO())
    text = csv.read_text()
    assert "peak:min:base" in text and "peak:min:head" in text  # one column per metric:stat:run
    assert "10485760" in text and "12582912" in text  # raw bytes, not unit-scaled


def test_sort_value_orders_rows_in_a_single_table(tmp_path):
    a = _write(tmp_path / "a.json", [_bm("small", peak=1024), _bm("big", peak=10 * 1024**2)])
    b = _write(tmp_path / "b.json", [_bm("small", peak=1024), _bm("big", peak=10 * 1024**2)])
    body = StringIO()
    compare_runs([a, b], columns="peak", group_by=None, sort="value", out=body)
    text = body.getvalue()
    assert text.index("big") < text.index("small")  # largest in the last run first


def test_sort_rejects_unknown_key(tmp_path):
    a = _write(tmp_path / "a.json", [_bm("x", peak=1)])
    b = _write(tmp_path / "b.json", [_bm("x", peak=2)])
    with pytest.raises(ValueError, match="unknown --sort"):
        compare_runs([a, b], columns="peak", sort="bogus", out=StringIO())


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
    compare_runs([a, b], columns="peak", stat="mean", out=out)
    rows = _lines(out.getvalue(), "test_x")
    assert "20" in rows and "50" in rows  # the per-run mean of each series


def test_stat_narrows_to_a_single_column(tmp_path):
    # --stat min collapses the spread to one column per metric
    a = _write(tmp_path / "a.json", [_bm("test_x", peak=10 * 1024**2)])
    b = _write(tmp_path / "b.json", [_bm("test_x", peak=12 * 1024**2)])
    out = StringIO()
    compare_runs([a, b], columns="peak", stat="min", out=out)
    text = out.getvalue()
    assert "min" in text and "median" not in text and "stddev" not in text


def test_stat_selects_the_time_distribution(tmp_path):
    # --stat reads pytest-benchmark's own stat for time too (here max), not just memory
    def _t(max_):
        return {
            "fullname": "test_x",
            "stats": {"min": 1.0, "max": max_, "mean": 2.0, "median": 2.0, "stddev": 0.5},
        }

    pa, pb = _write(tmp_path / "a.json", [_t(3.0)]), _write(tmp_path / "b.json", [_t(9.0)])
    out = StringIO()
    compare_runs([pa, pb], columns="time", stat="max", out=out)
    assert "9" in out.getvalue()  # head's max (9), not its min (1.0)


def test_unknown_stat_raises(tmp_path):
    a = _write(tmp_path / "a.json", [_bm("x", peak=1)])
    b = _write(tmp_path / "b.json", [_bm("x", peak=2)])
    with pytest.raises(ValueError, match="unknown --stat"):
        compare_runs([a, b], stat="p99", out=StringIO())


def test_three_runs_stack_as_rows_with_multipliers(tmp_path):
    # a cross-version sweep is N runs → one row per run, relative to the best run
    a = _write(tmp_path / "v1.json", [_bm("test_x", peak=1 * 1024**2)])
    b = _write(tmp_path / "v2.json", [_bm("test_x", peak=2 * 1024**2)])
    c = _write(tmp_path / "v3.json", [_bm("test_x", peak=4 * 1024**2)])
    out = StringIO()
    compare_runs([a, b, c], columns="peak", out=out)
    text = out.getvalue()
    assert "(v1)" in text and "(v2)" in text and "(v3)" in text  # one row per run
    assert "(2.00)" in text and "(4.00)" in text  # vs the best run (v1)
    assert "change" not in text  # no delta column in the relative-multiplier model


# --- --pivot: fold one run along a dim as the comparison series ----------------------


def _bm_dim(name, dims, *, peak):
    """A benchmark whose params (and thus its node-id payload) carry analysis dims."""
    bm = _bm(name, peak=peak)
    bm["params"] = dims
    return bm


def test_pivot_param_folds_single_run_along_the_dim(tmp_path):
    # semantics is a param *in the id* (test_build[legacy-100]) and a dim; --pivot param:semantics
    # pairs legacy↔v1 within one run — the role a run-file pair plays today — and the (N.NN)
    # multiplier ranks the dim values, not files.
    run = _write(
        tmp_path / "build.json",
        [
            _bm_dim(
                "m.py::test_build[legacy-100]", {"semantics": "legacy", "n": 100}, peak=10 * 1024**2
            ),
            _bm_dim("m.py::test_build[v1-100]", {"semantics": "v1", "n": 100}, peak=12 * 1024**2),
        ],
    )
    out = StringIO()
    compare_runs([run], columns="peak", pivot="param:semantics", out=out)
    text = out.getvalue()
    # the pivot token is lifted out of the id, so both rows fold under one group
    assert "m.py::test_build[100]" in text
    assert "(legacy)" in text and "(v1)" in text  # series = the dim's values
    assert "(1.20)" in text  # v1 peak 12 MiB is 1.20× the best (legacy 10 MiB)


def test_pivot_accepts_bare_extra_info_dim_not_in_id(tmp_path):
    # an extra_info dim isn't in the node id, so both rows already share an id and pair without
    # any id surgery; the bare name resolves the same as param:NAME.
    def _bm_mode(mode, peak):
        return {
            "fullname": "test_build",
            "stats": {s: 0.0 for s in ("min", "max", "mean", "median", "stddev")},
            "extra_info": {
                "benchmem": {"peak_bytes": [peak], "allocations": [1], "total_bytes": [1]},
                "mode": mode,
            },
        }

    rows = [_bm_mode("legacy", 10 * 1024**2), _bm_mode("v1", 15 * 1024**2)]
    run = _write(tmp_path / "build.json", rows)
    out = StringIO()
    compare_runs([run], columns="peak", pivot="mode", out=out)
    text = out.getvalue()
    assert "(legacy)" in text and "(v1)" in text
    assert "(1.50)" in text  # 15 MiB is 1.50× the best (10 MiB)


def test_pivot_with_multiple_runs_is_an_error(tmp_path):
    # one series axis per table: a dim within each run *and* runs-as-series is a 2-D matrix the
    # A/B view can't render, so --pivot + >1 run is rejected (scoped to a single combined run).
    a = _write(tmp_path / "a.json", [_bm_dim("t[legacy]", {"semantics": "legacy"}, peak=1024)])
    b = _write(tmp_path / "b.json", [_bm_dim("t[v1]", {"semantics": "v1"}, peak=2048)])
    with pytest.raises(ValueError, match="folds a single run"):
        compare_runs([a, b], columns="peak", pivot="param:semantics", out=StringIO())


def test_pivot_unknown_dim_errors_with_available(tmp_path):
    run = _write(tmp_path / "r.json", [_bm_dim("t[100]", {"n": 100}, peak=1024)])
    with pytest.raises(ValueError, match="not a dim"):
        compare_runs([run], columns="peak", pivot="param:nope", out=StringIO())


def test_pivot_warns_when_nothing_pairs(tmp_path):
    # custom-id style: the id token (L/V) differs from the param value, so the value never strips
    # out of the id → rows stay unpaired. Warn rather than silently show a pile of singletons.
    run = _write(
        tmp_path / "r.json",
        [
            _bm_dim("t[L]", {"semantics": "legacy"}, peak=100),
            _bm_dim("t[V]", {"semantics": "v1"}, peak=200),
        ],
    )
    with pytest.warns(UserWarning, match="left every row unpaired"):
        compare_runs([run], columns="peak", pivot="param:semantics", out=StringIO())


def test_pivot_gate_flags_growth_first_value_vs_last(tmp_path):
    # the gate generalizes along the pivot axis: base = first dim value (legacy), head = last
    # (v1), paired per folded id. legacy→v1 grows 100→130 (+30%) for n=1, 100→105 (+5%) for n=2.
    run = _write(
        tmp_path / "build.json",
        [
            _bm_dim("t[legacy-1]", {"semantics": "legacy", "n": 1}, peak=100),
            _bm_dim("t[v1-1]", {"semantics": "v1", "n": 1}, peak=130),
            _bm_dim("t[legacy-2]", {"semantics": "legacy", "n": 2}, peak=100),
            _bm_dim("t[v1-2]", {"semantics": "v1", "n": 2}, peak=105),
        ],
    )
    regs = find_pivot_regressions(run, "param:semantics", [parse_threshold("peak:10%")])
    # only the n=1 folded id grew past 10%; the folded id has semantics lifted out of the token
    assert [(r.id, round(r.pct)) for r in regs] == [("t[1]", 30)]


def test_pivot_gate_needs_two_values(tmp_path):
    # one combined run that doesn't actually vary the pivot dim → nothing to gate, loud error
    run = _write(tmp_path / "build.json", [_bm_dim("t[legacy]", {"semantics": "legacy"}, peak=100)])
    with pytest.raises(ValueError, match="two distinct values"):
        find_pivot_regressions(run, "param:semantics", [parse_threshold("peak:10%")])


# --- --format md: GitHub-flavored markdown ----------------------------------------


def test_markdown_format_emits_github_table(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("pkg::test_x", t=1.0, peak=10 * 1024**2)])
    b = _write(tmp_path / "head.json", [_bm("pkg::test_x", t=1.0, peak=12 * 1024**2)])
    out = StringIO()
    compare_runs([a, b], columns="peak", stat="min", out_format="md", out=out)
    text = out.getvalue()
    assert "#### pkg::test_x" in text  # one section per group (default group-by fullname)
    assert "| name | peak (MiB) min |" in text  # header with the scaled unit
    assert "| :--- | ---: |" in text  # left-aligned name, right-aligned metric
    assert "| (head) | 12.00 (1.20) |" in text  # value + multiplier, no colour
    assert "\x1b[" not in text and "─" not in text  # no ANSI, no rich box-drawing


def test_markdown_escapes_pipes_in_ids(tmp_path):
    # a literal pipe in a node id must not break the table grid; multi-id group → id is a row cell
    a = _write(tmp_path / "a.json", [_bm("test_x[a|b]", peak=1024), _bm("test_y", peak=2048)])
    out = StringIO()
    compare_runs([a], columns="peak", group_by=None, out_format="md", out=out)
    assert r"test_x[a\|b] (a)" in out.getvalue()  # pipe escaped inside the cell


def test_unknown_format_raises(tmp_path):
    a = _write(tmp_path / "a.json", [_bm("x", peak=1)])
    with pytest.raises(ValueError, match="unknown --format"):
        compare_runs([a], out_format="xml", out=StringIO())


# --- the diff view (--diff): metrics on the row axis, one Δ column per run --------


def test_diff_collapses_to_one_row_per_id_with_signed_delta(tmp_path):
    # single metric → the metric column is dropped; baseline value, then a Δ column per later run
    a = _write(tmp_path / "base.json", [_bm("pkg::test_x", peak=58 * 1024**2)])
    b = _write(tmp_path / "head.json", [_bm("pkg::test_x", peak=72 * 1024**2)])
    out = StringIO()
    compare_runs([a, b], columns="peak", group_by=None, diff=True, out_format="md", out=out)
    text = out.getvalue()
    assert "| name | peak base | head |" in text  # baseline value + the head run's Δ column
    assert "| test_x | 58 MiB | +24.1% |" in text  # one row: baseline value, then the Δ
    assert "72" not in text  # the head *absolute* is dropped as redundant (= base × 1.24)
    assert "(base)" not in text and "(head)" not in text  # collapsed: not two series rows


def test_diff_metrics_are_rows_not_columns(tmp_path):
    # multiple metrics → each is its own row under the id, columns stay flat (base + Δ per run)
    a = _write(tmp_path / "base.json", [_bm("test_x", t=1.0, peak=1024)])
    b = _write(tmp_path / "head.json", [_bm("test_x", t=2.0, peak=1024)])
    out = StringIO()
    compare_runs([a, b], columns="time,peak", group_by=None, diff=True, out_format="md", out=out)
    text = out.getvalue()
    assert "| name | metric | base | head |" in text  # a metric column, then base + one Δ
    assert (
        "| test_x | time |" in text and "|  | peak |" in text
    )  # id named once, blank continuation
    assert "mean" not in text and "median" not in text  # --stat defaults to just min under --diff
    assert "+100.0%" in text  # time doubled
    assert "0.0%" in text  # peak unchanged reads a plain 0.0%, no sign


def test_diff_needs_at_least_two_series(tmp_path):
    one = _write(tmp_path / "a.json", [_bm("x", peak=1)])
    with pytest.raises(ValueError, match="at least two series"):
        compare_runs([one], diff=True, out=StringIO())


def test_diff_over_three_runs_measures_each_against_the_first(tmp_path):
    # a sweep: baseline is the first run; every later run gets a Δ% column vs it (not vs previous)
    v1 = _write(tmp_path / "v1.json", [_bm("test_x", peak=10 * 1024**2)])
    v2 = _write(tmp_path / "v2.json", [_bm("test_x", peak=11 * 1024**2)])
    main = _write(tmp_path / "main.json", [_bm("test_x", peak=15 * 1024**2)])
    out = StringIO()
    compare_runs([v1, v2, main], columns="peak", diff=True, out_format="md", out=out)
    text = out.getvalue()
    # one baseline value column, then one Δ column per later run, each headed by its run label
    assert "| name | peak base | v2 | main |" in text
    assert "+10.0%" in text  # v2 11 MiB vs the v1 baseline (10) — not vs nothing
    assert "+50.0%" in text  # main 15 MiB vs the v1 baseline (10), NOT vs v2 (would be +36%)


def test_diff_over_a_pivot_pair(tmp_path):
    # a single run folded along a two-value dim is a valid base->head pair
    run = _write(
        tmp_path / "build.json",
        [
            _bm_dim("m.py::test_build[legacy]", {"semantics": "legacy"}, peak=10 * 1024**2),
            _bm_dim("m.py::test_build[v1]", {"semantics": "v1"}, peak=12 * 1024**2),
        ],
    )
    out = StringIO()
    compare_runs([run], columns="peak", diff=True, pivot="param:semantics", out=out)
    assert "+20.0%" in out.getvalue()  # legacy 10 MiB -> v1 12 MiB


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


def test_find_regressions_rss_detects_growth(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("x", peak=10, rss=1000)])
    b = _write(tmp_path / "head.json", [_bm("x", peak=10, rss=1200)])
    assert find_regressions(a, b, [parse_threshold("rss:10%")])  # +20%
    assert not find_regressions(a, b, [parse_threshold("rss:30%")])


def test_rss_gate_without_isolated_data_is_loud(tmp_path):
    # rss exists only for isolated runs; gating it against ordinary runs must ERROR, not
    # silently pass — a gate that can never fire is worse than one that fails (review #2).
    from pytest_benchmem.compare import memory_regressions

    a = _write(tmp_path / "base.json", [_bm("x", peak=10)])  # no rss
    b = _write(tmp_path / "head.json", [_bm("x", peak=10)])
    with pytest.raises(ValueError, match="isolate=True"):
        find_regressions(a, b, [parse_threshold("rss:10%")])

    blob = {"peak_bytes": [10], "allocations": [1], "total_bytes": [10]}  # in-process blob
    with pytest.raises(ValueError, match="isolate=True"):
        memory_regressions({"x": blob}, {"x": blob}, [parse_threshold("rss:10%")])


def test_compare_notes_when_rss_requested_but_absent(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("x", peak=10)])  # no rss
    b = _write(tmp_path / "head.json", [_bm("x", peak=20)])
    buf = StringIO()
    compare_runs([a, b], columns="peak,rss", out=buf)
    assert "rss not recorded" in buf.getvalue()  # not a silent column drop


def test_find_regressions_ignores_improvements(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("x", peak=200)])
    b = _write(tmp_path / "head.json", [_bm("x", peak=100)])  # halved — not a regression
    assert find_regressions(a, b, [parse_threshold("peak:1%")]) == []
