from __future__ import annotations

import json
from io import StringIO

import pytest

pytest.importorskip("pandas")

from pytest_benchmem.compare import compare_runs


def _write(path, benchmarks):
    path.write_text(json.dumps({"benchmarks": benchmarks}))
    return path


def _bm(name, *, t=0.0, mib=None):
    bm = {"fullname": name, "stats": {"min": t}}
    if mib is not None:
        bm["extra_info"] = {"peak_mib": mib}
    return bm


def _line(text, needle):
    return next(line for line in text.splitlines() if needle in line)


def test_percent_change_time(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("test_x", t=1.0), _bm("test_y", t=2.0)])
    b = _write(tmp_path / "head.json", [_bm("test_x", t=1.5), _bm("test_y", t=1.0)])
    out = StringIO()
    compare_runs(a, b, out=out)  # metric defaults to "time"
    text = out.getvalue()
    assert "(s)" in text  # unit in the header
    assert "+50.0%" in _line(text, "test_x")  # 1.0 -> 1.5
    assert "-50.0%" in _line(text, "test_y")  # 2.0 -> 1.0


def test_memory_metric_reads_extra_info(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("test_x", mib=10.0)])
    b = _write(tmp_path / "head.json", [_bm("test_x", mib=12.0)])
    out = StringIO()
    compare_runs(a, b, metric="memory", out=out)
    text = out.getvalue()
    assert "(MiB)" in text
    assert "+20.0%" in _line(text, "test_x")  # 10.0 -> 12.0


def test_one_sided_ids_show_dash(tmp_path):
    a = _write(tmp_path / "base.json", [_bm("only_a", t=1.0)])
    b = _write(tmp_path / "head.json", [_bm("only_b", t=2.0)])
    out = StringIO()
    compare_runs(a, b, out=out)
    text = out.getvalue()
    # each id is in only one run → the missing value column AND the change show —
    assert _line(text, "only_a").count("—") == 2
    assert _line(text, "only_b").count("—") == 2


def test_zero_baseline_suppresses_percent(tmp_path):
    # change is guarded by `va > 0`, so a 0 baseline can't divide-by-zero
    a = _write(tmp_path / "base.json", [_bm("test_x", t=0.0)])
    b = _write(tmp_path / "head.json", [_bm("test_x", t=1.0)])
    out = StringIO()
    compare_runs(a, b, out=out)
    assert _line(out.getvalue(), "test_x").rstrip().endswith("—")
