"""Template directory resolution tests (issue #98)."""

from autoinfo.output import _TEMPLATES_DIR


def test_templates_dir_exists() -> None:
    """_TEMPLATES_DIR must resolve to a real directory."""
    assert _TEMPLATES_DIR.is_dir(), f"Templates directory not found: {_TEMPLATES_DIR}"


def test_templates_dir_contains_expected_files() -> None:
    """The templates dir must contain the 7 expected Jinja2 templates."""
    files = sorted(f.name for f in _TEMPLATES_DIR.glob("*.j2"))
    assert len(files) >= 7, f"Expected >=7 .j2 templates, found {len(files)}: {files}"
    for expected in ("digest.md.j2", "digest.html.j2", "report.md.j2"):
        assert expected in files, f"Missing expected template: {expected}"
