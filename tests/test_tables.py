from __future__ import annotations

from io import StringIO

from rich.console import Console

from pytest_benchmem.memray import Measurement, MemoryResult
from pytest_benchmem.tables import _byte_unit, build_run_table, mem_columns


def _render(table, width=10_000):
    """Render a rich table to plain text (no color) for assertions."""
    if table is None:
        return ""
    buf = StringIO()
    Console(file=buf, width=width, color_system=None).print(table)
    return buf.getvalue()


def _blob(peak, *, peak_max=None, allocations=0, total_bytes=0, repeats=1):
    """A benchmem blob (flat per-repeat series). ``peak_max`` makes peak vary."""
    peaks = [peak] * repeats if peak_max is None else [peak, peak_max]
    n = len(peaks)
    return {"peak_bytes": peaks, "allocations": [allocations] * n, "total_bytes": [total_bytes] * n}


def _body(text):
    """Data rows only — drop the title, header, and rule lines."""
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("Memory") or set(s) <= {"━", "─", "-", " "}:
            continue
        if s.split()[0] == "name":  # header row
            continue
        rows.append(s)
    return rows


def test_empty_blobs_render_nothing():
    assert build_run_table({}) is None


def test_headers_and_short_names():
    blobs = {
        "mod.py::test_big": _blob(4 * 1024**2, allocations=1234, total_bytes=8 * 1024**2),
        "mod.py::test_small": _blob(1024, allocations=5, total_bytes=2048),
    }
    text = _render(build_run_table(blobs))
    assert "name" in text and "peak" in text and "allocated" in text and "allocs" in text
    assert "test_big" in text and "mod.py" not in text  # node-id prefix stripped


def test_sorted_by_peak_descending():
    blobs = {
        "t::a_small": _blob(1024),
        "t::b_huge": _blob(9 * 1024**2),
        "t::c_mid": _blob(3 * 1024**2),
    }
    names = [row.split()[0] for row in _body(_render(build_run_table(blobs)))]
    assert names == ["b_huge", "c_mid", "a_small"]


def test_constant_metric_stays_one_column():
    text = _render(build_run_table({"t::x": _blob(2048, repeats=3)}))  # constant across repeats
    assert "peak (KiB)" in text and "peak·min" not in text  # one column, not spread


def test_varying_metric_spreads_into_min_mean_max():
    blobs = {
        "t::flat": _blob(2048, repeats=1),
        "t::noisy": _blob(2048, peak_max=4096),  # peak varies across repeats
    }
    text = _render(build_run_table(blobs))
    assert "peak·min" in text and "peak·mean" in text and "peak·max" in text  # spread
    assert "allocs" in text and "allocs·min" not in text  # constant metric stays one column


def test_unit_hoisted_into_header_and_allocs_grouped():
    blobs = {"t::x": _blob(4 * 1024**2, allocations=1234567, total_bytes=2048)}
    text = _render(build_run_table(blobs))
    assert "peak (MiB)" in text and "4.00" in text  # unit in header, bare cell
    assert "1,234,567" in text  # thousands-separated count


def test_baseline_folds_in_columns_and_change():
    base = {"t::x": _blob(10 * 1024**2)}
    head = {"t::x": _blob(12 * 1024**2)}
    text = _render(build_run_table(head, baseline=base, baseline_label="0007"))
    assert "vs 0007" in text  # heading names the baseline
    assert "base (MiB)" in text and "change" in text  # extra columns, unit hoisted
    assert "10.00" in text and "12.00" in text  # baseline + current peak, in MiB
    assert "+20.0%" in text


def test_baseline_absent_id_shows_dash():
    base = {"t::old": _blob(1024)}
    head = {"t::new": _blob(2048)}  # a brand-new benchmark, not in the baseline
    rows = _body(_render(build_run_table(head, baseline=base)))
    assert rows and rows[0].split()[0] == "new"
    assert rows[0].count("—") == 2  # baseline cell AND change cell are —


def test_no_baseline_omits_compare_columns():
    text = _render(build_run_table({"t::x": _blob(2048)}))
    assert "base" not in text and "change" not in text


# --- the shared mem_columns logic ------------------------------------------------


def test_byte_unit_picks_from_largest():
    assert _byte_unit(0) == ("B", 1.0)
    assert _byte_unit(2048)[0] == "KiB"
    assert _byte_unit(5 * 1024**2)[0] == "MiB"


def test_mem_columns_spreads_only_varying_metrics():
    varying = MemoryResult((Measurement(1024, 1, 10), Measurement(4096, 1, 10)))  # only peak varies
    headers = [c.header for c in mem_columns([varying])]
    assert headers == ["peak·min (KiB)", "peak·mean", "peak·max", "allocated (B)", "allocs"]


def test_mem_columns_all_constant_single_columns():
    const = MemoryResult((Measurement(1024, 5, 2048),))
    headers = [c.header for c in mem_columns([const])]
    assert headers == ["peak (KiB)", "allocated (KiB)", "allocs"]


def test_mem_columns_compute_distribution():
    res = MemoryResult((Measurement(1024, 1, 1), Measurement(2048, 1, 1), Measurement(4096, 1, 1)))
    cols = {c.header: c.cell for c in mem_columns([res])}
    assert cols["peak·min (KiB)"](res) == "1.00"  # min / 1024
    assert cols["peak·max"](res) == "4.00"
    assert cols["peak·mean"](res) == "2.33"  # (1024+2048+4096)/3 / 1024
