"""Repo files that hosting depends on."""
from pathlib import Path


def test_requirements_are_plain_utf8():
    # PowerShell's ">" writes UTF-16, which pip on Render cannot read ("Invalid requirement: 'f\x00a\x00...'")
    for name in ("requirements.txt", "requirements-dev.txt"):
        raw = Path(name).read_bytes()
        assert b"\x00" not in raw and not raw.startswith((b"\xff\xfe", b"\xfe\xff")), f"{name} must be saved as UTF-8"
        raw.decode("utf-8")


def test_requirements_have_no_windows_only_packages():
    text = Path("requirements.txt").read_text(encoding="utf-8").lower()
    assert "pywin32" not in text  # breaks the Linux build on Render
