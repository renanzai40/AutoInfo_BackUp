"""Coverage-completion tests for ``autoinfo.validation_matrix`` (#347/#348).

The baseline-aware coverage gate requires changed modules to hold their
merge-base coverage (2pp tolerance).  The #348 smart-skip implementation
added new real paths (git subprocess, KB filesystem scan, batch-history
error handling) that the unit tests patch over.  These tests exercise those
real, unpatched branches deterministically — no LLM, no network — so the
module keeps its coverage and the real paths are verified at the same time.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from autoinfo import validation_matrix as vm


def test_load_batch_history_handles_missing_and_corrupt(tmp_path: Path) -> None:
    """_load_batch_history tolerates a missing dir, non-dir entries, corrupt
    JSON and non-JSON files without raising."""
    missing = tmp_path / "nope"
    assert vm._load_batch_history(missing) == []

    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "not-a-dir.txt").write_text("x", encoding="utf-8")
    bad_batch = snap / "bad"
    bad_batch.mkdir()
    (bad_batch / "report-card-bad.json").write_text("{not json", encoding="utf-8")
    good_batch = snap / "good"
    good_batch.mkdir()
    (good_batch / "report-card-good.json").write_text(
        json.dumps({"generated_at": "2026-08-01T00:00:00Z", "batch_id": "g",
                    "products": []}),
        encoding="utf-8",
    )
    history = vm._load_batch_history(snap)
    assert len(history) == 1
    assert history[0]["batch_id"] == "g"


def test_no_error_leak_flags_traceback() -> None:
    """_no_error_leak catches a Python traceback in the product header."""
    leaky = "# T\n\nTraceback (most recent call last):\n  File \"x\", line 1\n"
    r = vm._no_error_leak(leaky, "d", "report")
    assert not r.passed
    assert "traceback" in r.details


def test_no_placeholder_flags_skeleton_echo() -> None:
    """_collect_placeholder_tokens catches residual LLM skeleton echoes."""
    text = "# T\n\n<finding 1>\n\nSome body text.\n"
    assert "<finding 1>" in vm._collect_placeholder_tokens(text)
    assert not vm._no_placeholder(text, "d", "report").passed


def test_report_sections_fallback_without_metadata() -> None:
    """_report_sections falls back to structural checks when no Sections
    metadata line exists (empty shell -> fail, substantive body -> pass)."""
    shell = "# T\n\n## Summary\n\nshort\n"
    assert not vm._report_sections(shell, "d", "report").passed
    substantive = (
        "# T\n\n## Summary\n\n" + "word " * 250 + "\n\n## Deep Dive\n\nbody\n"
    )
    assert vm._report_sections(substantive, "d", "report").passed


def test_current_commit_unknown_on_git_failure() -> None:
    """_current_commit returns 'unknown' (never raises) when git fails."""
    with patch("autoinfo.validation_matrix.subprocess.run",
               side_effect=FileNotFoundError("no git")):
        assert vm._current_commit() == "unknown"


def test_card_issue_counts_breaks_down_missing_and_error() -> None:
    """card_issue_counts classifies missing/error products + failing
    assertions independently (the #336 breakdown)."""
    card = {
        "products": [
            {"product": "a", "status": "ok",
             "assertions": [{"assertion": "_not_empty", "passed": False}]},
            {"product": "b", "status": "missing", "assertions": []},
            {"product": "c", "status": "error", "assertions": [], "error": "boom"},
            {"product": "d", "status": "ok",
             "assertions": [{"assertion": "_not_empty", "passed": True}]},
        ]
    }
    counts = vm.card_issue_counts(card)
    assert counts == {
        "failing_assertions": 1, "missing_products": 1, "error_products": 1,
    }


def test_code_changed_real_git_roundtrip(tmp_path: Path) -> None:
    """_code_changed's real git path: no diff -> False; touched file -> True;
    empty template_paths -> False; git error -> True (fail-safe)."""
    # No template paths -> False without touching git.
    assert vm._code_changed("HEAD", "report", "d", []) is False

    # A real temp git repo where we can diff two states deterministically.
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "tpl").mkdir()
    (repo / "tpl" / "report.md.j2").write_text("v1", encoding="utf-8")
    (repo / "autoinfo").mkdir()
    (repo / "autoinfo" / "output.py").write_text("print(1)\n", encoding="utf-8")
    old = Path.cwd()
    try:
        import os
        import subprocess

        os.chdir(repo)
        for cmd in (
            ["git", "init", "-q"],
            ["git", "config", "user.email", "t@t"],
            ["git", "config", "user.name", "t"],
            ["git", "add", "."],
            ["git", "commit", "-qm", "base"],
        ):
            subprocess.run(cmd, check=True, capture_output=True)
        base = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        # No change yet.
        assert vm._code_changed(
            base, "report", "d", ["tpl", "autoinfo/output.py"]
        ) is False
        # Touch a template file, commit it.
        (repo / "tpl" / "report.md.j2").write_text("v2", encoding="utf-8")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "touch"], check=True, capture_output=True)
        assert vm._code_changed(
            base, "report", "d", ["tpl", "autoinfo/output.py"]
        ) is True
    finally:
        os.chdir(old)


def test_code_changed_git_error_is_failsafe() -> None:
    """_code_changed returns True (regenerate) when git itself errors."""
    with patch("autoinfo.validation_matrix.subprocess.run",
               side_effect=RuntimeError("boom")):
        assert vm._code_changed("c1", "report", "d", ["tpl"]) is True


def test_raw_entry_count_real_kb_scan(tmp_path: Path) -> None:
    """_raw_entry_count counts .md files recursively under
    <data_dir>/<domain>/01-Raw/ and returns 0 for a missing dir."""
    kb = tmp_path / "kb"
    assert vm._raw_entry_count("ai-commercial", kb) == 0
    raw = kb / "ai-commercial" / "01-Raw" / "topic-a"
    raw.mkdir(parents=True)
    (raw / "2026-08-01-entry.md").write_text("x", encoding="utf-8")
    (raw / "2026-08-02-entry.md").write_text("y", encoding="utf-8")
    raw_b = kb / "ai-commercial" / "01-Raw" / "topic-b"
    raw_b.mkdir(parents=True)
    (raw_b / "2026-08-03.md").write_text("z", encoding="utf-8")
    assert vm._raw_entry_count("ai-commercial", kb) == 3


# ---------------------------------------------------------------------------
# #351 — unpatched-branch coverage for the four new hard security assertions.
# These tests exercise the REAL regex branches the implementer will add; they
# fail RED today (AttributeError) and must pass GREEN with the implementer's
# module constants (_MIN_PLAUSIBLE_YEAR / _YEAR_RE / _MONTH_YEAR_RE /
# _FENCE / _KEY_SHAPES / _REF_URL_TOKEN / _EXT_ERROR_*) in place.
# ---------------------------------------------------------------------------


def test_year_regex_edges() -> None:
    """_no_year_hallucination's real regex branches: a bare month-year form is
    pinned as P1 when its YEAR is out of range (future / pre-1950); future
    years asserted as completed facts are P0, pre-1950 years are P1 "human
    review"; the year regex does not fire on 4-digit runs inside URLs or on
    plausible years; a bare month-year with a plausible year (1950..current
    year) passes (#351 tuning); the References section (from the
    ``## References`` heading) is excluded from scanning."""
    r = vm._no_year_hallucination("# T\n\nJuly 2023\n", "d", "report")
    assert r.passed  # plausible bare month-year — NOT flagged (#351 tuning)
    assert r.severity == "P1"
    r = vm._no_year_hallucination("# T\n\nIn March 2031, adoption tripled\n", "d", "report")
    assert not r.passed
    assert r.severity == "P0"
    r = vm._no_year_hallucination("# T\n\nback in June 1850, the crisis deepened\n", "d", "report")
    assert not r.passed
    assert r.severity == "P1"  # pre-1950 → P1 human review, not P0 (#351 V4)
    r = vm._no_year_hallucination("# T\n\nIn 2031, adoption tripled\n", "d", "report")
    assert not r.passed
    assert r.severity == "P0"
    r = vm._no_year_hallucination("# T\n\na 1947 patent\n", "d", "report")
    assert not r.passed
    assert r.severity == "P1"  # pre-1950 → P1 human review, not P0 (#351 V4)
    # Plausible years, plausible bare month-years and URL-embedded 4-digit
    # runs pass in prose — the #351 false-positive class is gone.
    assert vm._no_year_hallucination(
        "# T\n\nFounded in 2024, growth continued.\n", "d", "report"
    ).passed
    assert vm._no_year_hallucination(
        "# T\n\nIn March 2020, the market crashed\n", "d", "report"
    ).passed
    assert vm._no_year_hallucination(
        "# T\n\nfounded in June 1995\n", "d", "report"
    ).passed
    assert vm._no_year_hallucination(
        "# T\n\nSee https://example.com/2023-report\n", "d", "report"
    ).passed
    # References section is exempt: old citation years must not fail.
    refs = "# T\n\nbody\n\n## References\n\n1. **A** — https://x.com (1999)\n"
    assert vm._no_year_hallucination(refs, "d", "report").passed


def test_key_regex_length_thresholds() -> None:
    """_no_code_or_key_leak's real length thresholds: short hex/base64 tokens
    (below the 32-char hex / 40-char base64 cutoffs) pass, long runs fail,
    and the prefix shapes (sk-/AIza/AKIA/ghp_/eyJ) fail at any length."""
    # Long hex run (>=32 chars) fails; short hex passes.
    long_hex = "0" * 32
    assert not vm._no_code_or_key_leak(
        f"# T\n\ntoken {long_hex}\n", "d", "report"
    ).passed
    assert vm._no_code_or_key_leak(
        "# T\n\nsha1 0a1b2c3d4e5f\n", "d", "report"
    ).passed
    # Long base64 (>=40 chars) fails; a short base64-looking slug passes.
    long_b64 = "a" * 40
    assert not vm._no_code_or_key_leak(
        f"# T\n\npayload {long_b64}==\n", "d", "report"
    ).passed
    assert vm._no_code_or_key_leak(
        "# T\n\nid abcdefghijklmnop\n", "d", "report"
    ).passed
    # Prefix shapes fail regardless of length.
    assert not vm._no_code_or_key_leak("# T\n\nsk-abc\n", "d", "report").passed
    assert not vm._no_code_or_key_leak("# T\n\nghp_abc\n", "d", "report").passed


def test_reference_url_parse_edges() -> None:
    """_no_broken_reference's real parse branches: empty View Source targets,
    scheme-less targets, and bare (identifier) placeholders fail; the legit
    identifier schemes (doi:/pmid:/arxiv:/isbn:) pass."""
    assert not vm._no_broken_reference(
        "# T\n\n[View Source]()\n", "d", "report"
    ).passed
    assert not vm._no_broken_reference(
        "# T\n\n[View Source](not a url)\n", "d", "report"
    ).passed
    assert not vm._no_broken_reference(
        "# T\n\n## References\n\n1. **A** — (pubmed)\n", "d", "report"
    ).passed
    assert vm._no_broken_reference(
        "# T\n\n[View Source](https://example.com/a)\n", "d", "report"
    ).passed
    assert vm._no_broken_reference(
        "# T\n\n## References\n\n1. **A** — (doi:10.1000/xyz123)\n",
        "d", "report",
    ).passed
    assert vm._no_broken_reference(
        "# T\n\n## References\n\n1. **A** — (arxiv:2301.00001)\n",
        "d", "report",
    ).passed


def test_whole_body_ansi_beyond_500() -> None:
    """_no_external_error_text scans the WHOLE body for ANSI escapes — the
    #351 gap where _no_error_leak only checks ``text[:500]``.  A code with a
    legit bare link (no ANSI) must pass."""
    ansi_beyond_500 = ("plain body text " * 40) + "\x1b[1;31mred\x1b[0m\n"
    r = vm._no_external_error_text(ansi_beyond_500, "d", "report")
    assert not r.passed
    clean = "# T\n\n[View Source](https://example.com/a)\n"
    assert vm._no_external_error_text(clean, "d", "report").passed
