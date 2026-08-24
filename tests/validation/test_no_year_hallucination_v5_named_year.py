"""Tests for the #351 V5 named-year exemption in ``_no_year_hallucination``.

V5 closes a false-positive class introduced by the #351 year-hallucination
gate: a FUTURE year used as part of a title/list/guide/ranking/survey/
publication NAME ("The Princeton Review's 2027 Best Colleges guide") is a
legitimate reference — the year names the edition of the guide — not a
hallucinated fact.  Those must PASS.  Bare future years asserted as
completed facts ("In 2031, adoption tripled") must STILL fail P0, and
pre-1950 years ("founded in 1917") must STILL fail P1 "human review".

Deterministic unit test: no LLM, no network.  Exercises the real
``_no_year_hallucination`` paths directly.
"""

from __future__ import annotations

from autoinfo import validation_matrix as vm


def test_named_year_guide_title_passes() -> None:
    """A future year inside a publication/guide NAME is legitimate — the year
    identifies the edition, not a hallucinated fact.  Pre-V5 this fired a P0
    false positive on the bare ``2027``; V5 exempts the name-shaped run."""
    r = vm._no_year_hallucination(
        "# T\n\nThe Princeton Review's 2027 Best Colleges guide ranks the "
        "top 10 colleges for financial aid.\n",
        "financial-intelligence",
        "report",
    )
    assert r.passed, r.details
    assert r.severity != "P0"


def test_named_year_guide_title_without_owner_passes() -> None:
    """The owner-possessive prefix is optional — "The 2027 Best Colleges
    guide is out now." is still a name-shaped run, not a hallucination."""
    r = vm._no_year_hallucination(
        "# T\n\nThe 2027 Best Colleges guide is out now.\n",
        "financial-intelligence",
        "report",
    )
    assert r.passed, r.details


def test_named_year_publication_name_passes() -> None:
    """A possessive publication name before the year (Bloomberg's 2027
    outlook ... list) is exempted by V5."""
    r = vm._no_year_hallucination(
        "# T\n\nBloomberg's 2027 outlook lists the key risks.\n",
        "financial-intelligence",
        "report",
    )
    assert r.passed, r.details


def test_bare_future_fact_still_p0_fails() -> None:
    """V5 must NOT weaken the P0 gate: a bare future year asserted as a
    completed fact still fails hard."""
    r = vm._no_year_hallucination(
        "# T\n\nIn 2031, adoption tripled\n",
        "financial-intelligence",
        "report",
    )
    assert not r.passed
    assert r.severity == "P0"


def test_bare_future_month_year_still_p0_fails() -> None:
    """Bare future month-years ("In March 2031, adoption tripled") still
    fail P0 — the named-year exemption only covers name-shaped runs."""
    r = vm._no_year_hallucination(
        "# T\n\nIn March 2031, adoption tripled\n",
        "financial-intelligence",
        "report",
    )
    assert not r.passed
    assert r.severity == "P0"


def test_pre_1950_still_p1_human_review() -> None:
    """Pre-1950 years ("founded in 1917") still surface P1 "human review"
    for the human to judge — V4's design intent is preserved by V5."""
    r = vm._no_year_hallucination(
        "# T\n\nFounded in 1917, the bank survived two wars.\n",
        "financial-intelligence",
        "report",
    )
    assert not r.passed
    assert r.severity == "P1"
    assert "human review" in r.details
