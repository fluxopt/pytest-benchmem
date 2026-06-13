from __future__ import annotations

import pytest

from pytest_benchmem.sweep import _PLAIN_VERSION_RE, version_label


@pytest.mark.parametrize(
    "version, expected",
    [
        ("1.2.3", "1.2.3"),
        ("pkg@main", "main"),  # part after the last @
        ("git+https://github.com/me/pkg@v1.0", "v1.0"),
        ("feature/foo bar", "feature-foo-bar"),  # sanitized
        ("v2.0.0a1", "v2.0.0a1"),
    ],
)
def test_version_label(version, expected):
    assert version_label(version) == expected


@pytest.mark.parametrize("version", ["@@@", "///", "   "])
def test_version_label_falls_back_to_spec(version):
    assert version_label(version) == "spec"


@pytest.mark.parametrize("version", ["1", "1.2", "1.2.3", "1.2.3a1", "2.0b2"])
def test_plain_version_re_accepts_plain_versions(version):
    assert _PLAIN_VERSION_RE.match(version) is not None


@pytest.mark.parametrize(
    "spec", ["pkg==1.2", "git+https://x@main", "1.2.dev0", "1.2.3@main", ""]
)
def test_plain_version_re_rejects_pip_specs(spec):
    assert _PLAIN_VERSION_RE.match(spec) is None
