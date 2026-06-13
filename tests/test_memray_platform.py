"""The unsupported-platform guard — runs everywhere (fakes the OS), needs no memray."""

from __future__ import annotations

import pytest

import pytest_benchmem.memray as memray_mod


def test_measure_peak_raises_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr(memray_mod.platform, "system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="only Linux and macOS"):
        memray_mod.measure_peak(lambda: None)
