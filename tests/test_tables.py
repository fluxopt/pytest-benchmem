from __future__ import annotations

from io import StringIO

from rich.console import Console

from pytest_benchmem.tables import build_run_table


def _render(table, width=120):
    """Render a rich table to plain text (no color) for assertions."""
    if table is None:
        return ""
    buf = StringIO()
    Console(file=buf, width=width, color_system=None).print(table)
    return buf.getvalue()


def _blob(peak, *, peak_max=None, allocations=0, total_bytes=0, repeats=1):
    return {
        "peak_bytes": peak,
        "peak_bytes_max": peak if peak_max is None else peak_max,
        "allocations": allocations,
        "total_bytes": total_bytes,
        "repeats": repeats,
    }


def _body(text):
    """Data rows only — drop the title, header, and rule lines."""
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("Memory") or set(s) <= {"━", "─", "-", " "}:
            continue
        if s.split()[0] in {"name"}:  # header row
            continue
        rows.append(s)
    return rows


def test_empty_blobs_render_nothing():
    assert build_run_table({}) is None


def test_heap_table_headers_and_short_names():
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


def test_max_column_hidden_without_repeats():
    text = _render(build_run_table({"t::x": _blob(2048, repeats=1)}))
    assert " max " not in text and "max\n" not in text


def test_max_column_shown_when_any_repeat_spreads():
    blobs = {
        "t::flat": _blob(2048, repeats=1),
        "t::spread": _blob(2048, peak_max=4096, repeats=3),
    }
    assert "max" in _render(build_run_table(blobs))


def test_bytes_autoscale_and_allocs_grouped():
    blobs = {"t::x": _blob(4 * 1024**2, allocations=1234567, total_bytes=2048)}
    text = _render(build_run_table(blobs))
    assert "4 MiB" in text  # human_bytes auto-scale
    assert "1,234,567" in text  # thousands-separated count


def test_missing_field_renders_dash():
    blob = _blob(2048)
    del blob["total_bytes"]
    assert "—" in _render(build_run_table({"t::x": blob}))


def test_baseline_folds_in_columns_and_change():
    base = {"t::x": _blob(10 * 1024**2)}
    head = {"t::x": _blob(12 * 1024**2)}
    text = _render(build_run_table(head, baseline=base, baseline_label="0007"))
    assert "vs 0007" in text  # heading names the baseline
    assert "baseline" in text and "change" in text  # extra columns appear
    assert "10 MiB" in text and "12 MiB" in text  # baseline + current peak
    assert "+20.0%" in text


def test_baseline_absent_id_shows_dash():
    base = {"t::old": _blob(1024)}
    head = {"t::new": _blob(2048)}  # a brand-new benchmark, not in the baseline
    rows = _body(_render(build_run_table(head, baseline=base)))
    assert rows and rows[0].split()[0] == "new"
    assert rows[0].count("—") == 2  # baseline cell AND change cell are —


def test_no_baseline_omits_compare_columns():
    text = _render(build_run_table({"t::x": _blob(2048)}))
    assert "baseline" not in text and "change" not in text
