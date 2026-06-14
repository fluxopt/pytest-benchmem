from __future__ import annotations

from io import StringIO

from rich.console import Console

from pytest_benchmem.tables import build_compare_table, build_run_table


def _render(table, width=120):
    """Render a rich table to plain text (no color) for assertions."""
    if table is None:
        return ""
    buf = StringIO()
    Console(file=buf, width=width, color_system=None).print(table)
    return buf.getvalue()


def _blob(peak, *, peak_max=None, allocations=0, total_bytes=0, repeats=1, mode="heap"):
    return {
        "peak_bytes": peak,
        "peak_bytes_max": peak if peak_max is None else peak_max,
        "allocations": allocations,
        "total_bytes": total_bytes,
        "repeats": repeats,
        "mode": mode,
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


def test_rss_mode_swaps_churn_for_gross():
    blob = _blob(5 * 1024**2, mode="rss")
    blob["gross_bytes"] = 7 * 1024**2
    text = _render(build_run_table({"t::x": blob}))
    assert "gross" in text and "allocated" not in text and "allocs" not in text
    assert "(rss)" in text


def test_missing_field_renders_dash():
    blob = _blob(2048)
    del blob["total_bytes"]
    assert "—" in _render(build_run_table({"t::x": blob}))


def test_compare_table_shared_ids_and_change():
    base = {"t::x": _blob(10 * 1024**2), "t::only_base": _blob(1024)}
    head = {"t::x": _blob(12 * 1024**2), "t::only_head": _blob(2048)}
    text = _render(build_compare_table(base, head, baseline_label="0007"))
    assert "Memory vs baseline (peak)" in text
    assert "0007" in text  # baseline label in the column header
    assert "10 MiB" in text and "12 MiB" in text
    assert "+20.0%" in text
    assert "only_base" not in text and "only_head" not in text  # only shared ids


def test_compare_table_no_overlap_returns_none():
    assert build_compare_table({"t::a": _blob(1)}, {"t::b": _blob(2)}) is None
