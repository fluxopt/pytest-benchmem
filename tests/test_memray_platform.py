"""The unsupported-platform guard — runs everywhere (fakes the OS), needs no memray."""

from __future__ import annotations

import pytest

from pytest_benchmem import measure_peak


def test_measure_peak_raises_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr("pytest_benchmem.memray.platform.system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="only Linux and macOS"):
        measure_peak(lambda: None)
