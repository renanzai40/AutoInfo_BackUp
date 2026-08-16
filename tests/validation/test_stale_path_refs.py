"""Regression guard for #165: stale ``tests/test_stripe.py`` path references.

The stripe test module lives at ``tests/cost/test_stripe.py``. Two docs
referenced the old bare path ``tests/test_stripe.py``, and the
``TestStripeLifecycle`` docstring suggested running it with the bare
``python3`` interpreter against the wrong path. These assertions pin the
corrected references so the stale path cannot creep back.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRIAGE_MD = REPO_ROOT / "tests" / "TRIAGE.md"
TEST_STRIPE = REPO_ROOT / "tests" / "cost" / "test_stripe.py"

STALE_PATH = "tests/test_stripe.py"
CORRECT_PATH = "tests/cost/test_stripe.py"


def test_triage_md_has_no_stale_stripe_path() -> None:
    """tests/TRIAGE.md must reference the stripe module via its real path."""
    text = TRIAGE_MD.read_text(encoding="utf-8")
    assert STALE_PATH not in text, (
        f"tests/TRIAGE.md still references stale path {STALE_PATH!r}"
    )
    assert CORRECT_PATH in text, (
        f"tests/TRIAGE.md does not reference the corrected path {CORRECT_PATH!r}"
    )


def test_stripe_docstring_has_no_stale_path_and_uses_venv_python() -> None:
    """TestStripeLifecycle docstring must use the corrected path + interpreter."""
    text = TEST_STRIPE.read_text(encoding="utf-8")
    assert STALE_PATH not in text, (
        f"tests/cost/test_stripe.py still references stale path {STALE_PATH!r}"
    )
    expected_invocation = (
        ".venv/bin/python -m pytest "
        f"{CORRECT_PATH}::TestStripeLifecycle -v"
    )
    assert expected_invocation in text, (
        "TestStripeLifecycle docstring is missing the corrected invocation "
        f"{expected_invocation!r}"
    )
