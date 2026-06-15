"""mkdocs-macros hooks.

Render reference tables straight from the source of truth so the docs can't drift.
Custom jinja delimiters (``[[[ ... ]]]``) are configured in mkdocs.yml so ordinary
``{{ ... }}`` in the docs (e.g. GitHub Actions ``${{ }}``) is left untouched.
"""

from __future__ import annotations


def define_env(env):
    """Register mkdocs-macros macros (called by the plugin at build time)."""

    @env.macro
    def pytest_flags_table() -> str:
        """Render the pytest-benchmem CLI flags table from ``pytest_addoption``'s help text."""
        from pytest_benchmem.pytest_plugin import pytest_addoption

        rows: list[tuple[tuple, dict]] = []

        class _Group:
            def addoption(self, *names, **kwargs):
                rows.append((names, kwargs))

        class _Parser:
            def getgroup(self, *args, **kwargs):
                return _Group()

        pytest_addoption(_Parser())

        lines = ["| Flag | Default | What |", "|---|---|---|"]
        for names, kwargs in rows:
            metavar = kwargs.get("metavar")
            display = f"{names[0]}={metavar}" if metavar else names[0]
            default = kwargs.get("default")
            if kwargs.get("action") == "store_true" or default is False:
                shown_default = "off"
            elif default is None:
                shown_default = "—"
            else:
                shown_default = f"`{default}`"
            help_text = " ".join((kwargs.get("help") or "").split())
            lines.append(f"| `{display}` | {shown_default} | {help_text} |")
        return "\n".join(lines)
