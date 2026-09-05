"""Concierge MVP pilot CLI (``autoinfo mvp``, plan todo 13).

``mvp init`` provisions a complete paying pilot end-to-end:

1. **EndUserProfile + Subscription** — the profile is provisioned with
   ``tier="premium"`` / ``status="active"`` DIRECTLY
   (:func:`autoinfo.user_store.create_profile`).  The premium fast path of
   :func:`autoinfo.billing.check_access` reads ``UserProfile.tier``
   (billing.py:736-750), NOT the subscription tier — so a
   ``tier="premium"``/``status="active"`` profile grants premium access
   with NO Stripe dependency.  A bare
   :func:`autoinfo.user_store.activate_trial` would set ``status="trial"``
   and fall through to the Stripe fallback (rejected without Stripe) — it
   is deliberately NOT used here.  A matching premium subscription row is
   created alongside.
2. **Demo domain import** — reuses ``domain.py`` ``import_cmd`` (the
   ``import --from-demo`` source of truth) so the pilot domain config is
   byte-identical to a hand-imported demo domain.  Idempotent.
3. **First product** — generated through the HERMETIC SEAM (KBStore + LLM
   injection, mirror of ``regression-no-placeholder-magazine-tutorial``):
   static fixture entries with complete source provenance are injected
   through a patched ``KBStore`` and every LLM seam is patched to its
   deterministic fallback, so a temp project with NO LLM key and NO
   network still produces a REAL, complete product (which honestly passes
   the D1-D3 delivery gates — not an empty shell).
4. **Delivery directory** — ``mvp/<user_id>/`` (sibling of ``outputs/``)
   receives the product file, its gate report (md + json, shared todo-7
   implementation from :mod:`autoinfo.delivery.gate_report`),
   ``provenance.json`` (per-entry source provenance + explicit hermetic
   disclosure), and a ``user.json`` placeholder metadata file.

``mvp list`` aggregates pilot users from the filesystem + user_store
(profile tier/status) + subscriptions (plan) and shows each pilot's latest
product path.  Every step of ``init`` is idempotent: re-running prints a
clear ``already exists`` message and creates no duplicates.

Must NOT (plan todo 13): no trial reminders, no email delivery, no
scheduling, no Stripe, no external channel delivery, no LLM/network calls.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import typer

from autoinfo.config import get_config_path

app = typer.Typer(help="Concierge MVP pilots: provision and list paying pilot users")

_VALID_PRODUCTS = ("digest", "report", "premium-briefing")
_VALID_FREQUENCIES = ("daily", "weekly")

_NO_CONFIG_ERROR = (
    "Error: No configuration found. Run 'autoinfo init' first. "
    "See docs/dev/required-api-keys.md for API key setup."
)


def _existing_product_files(user_dir: Path) -> list[Path]:
    """Product markdown files in *user_dir* (gate reports excluded)."""
    return [
        p for p in user_dir.glob("*.md") if not p.name.startswith("gate-report-")
    ]


# ---------------------------------------------------------------------------
# Hermetic first-product seam
# ---------------------------------------------------------------------------


def _hermetic_entries() -> list[dict[str, Any]]:
    """Static fixture entries injected through the patched KBStore.

    Realistic (non-placeholder) titles/summaries with complete source
    provenance (source_url / source_type / source_platform) and a fresh
    ``collected_at`` (1 day ago) so D3-Freshness does not false-reject.
    The ``pubmed`` platform matches the seeded medical-research domain
    config, so the selection-time source-drift filter (#119) keeps them.
    """
    collected = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    base: list[tuple[str, str]] = [
        (
            "Time-lapse imaging improves live-birth rates in IVF cohorts",
            "A multicenter study reports a statistically significant improvement "
            "in live-birth rates when embryos are monitored via time-lapse "
            "imaging before transfer.",
        ),
        (
            "Neuroplasticity markers predict recovery in stroke rehabilitation",
            "Longitudinal data link early neuroplasticity markers to better "
            "motor-recovery outcomes in structured post-stroke rehabilitation "
            "programs.",
        ),
        (
            "Genomic screening reshapes reproductive-medicine clinical pathways",
            "A guideline update now recommends expanded genomic screening "
            "before assisted reproductive treatment in selected patient "
            "cohorts.",
        ),
    ]
    entries: list[dict[str, Any]] = []
    for i, (title, summary) in enumerate(base, start=1):
        entries.append(
            {
                "entry_id": f"mvp-fixture-{i}",
                "title": title,
                "summary": summary,
                "content": summary,
                "source_url": f"https://pubmed.ncbi.nlm.nih.gov/3400000{i}/",
                "source_type": "api",
                "source_platform": "pubmed",
                "source_label": "PubMed",
                "relevance_score": 90.0 - i,
                "tags": "[]",
                "tier": "01-Raw",
                "collected_at": collected,
                "domain": "medical-research",
            }
        )
    return entries


def _generate_first_product(
    product: str,
    domain: str,
    period: str,
    user_id: str,
    user_dir: Path,
) -> tuple[Path, list[dict[str, Any]]]:
    """Generate the pilot's first product via the hermetic seam.

    Patch set (mirror of ``regression-no-placeholder-magazine-tutorial`` /
    ``tests/output/test_product_routing.py``):

    - ``autoinfo.output.KBStore`` — static fixture entries injected
    - ``autoinfo.llm.LLMExtractor.extract`` — empty deterministic extraction
    - ``autoinfo.output._call_llm_for_digest`` — ``{}`` → the digest path
      fills synthesis deterministically from the real entries (#217 fallback)
    - report path additionally: ``_group_by_theme`` (one static group),
      ``_generate_executive_summary`` (static synthesis),
      ``_call_llm_for_report_synthesis`` (empty)

    Returns ``(product_path, fixture_entries)``.  Never touches the network
    or an LLM endpoint.
    """
    from unittest.mock import MagicMock, patch

    from autoinfo.models import ExtractionResult
    from autoinfo.output import (
        PRODUCT_TEMPLATES,
        generate_digest,
        generate_report,
    )

    entries = _hermetic_entries()
    generated_at = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    file_name = f"{product}-{period}-{generated_at}.md"

    empty_extract = ExtractionResult(item_id="mvp-seam", title="", custom_fields={})
    group = [
        {
            "theme": "Clinical Developments",
            "description": (
                "Recent peer-reviewed findings tracked for this pilot domain."
            ),
            "entries": entries,
        }
    ]
    synthesis = {
        "executive_summary": (
            f"This briefing summarizes three recent peer-reviewed developments "
            f"tracked for the {domain} pilot: time-lapse IVF monitoring, "
            "neuroplasticity-based stroke rehabilitation, and expanded genomic "
            "screening in reproductive medicine."
        ),
        "key_findings": [e["summary"] for e in entries],
        "recommendations": [
            "Monitor the time-lapse IVF evidence base for guideline updates.",
            "Track neuroplasticity-marker validation in larger cohorts.",
            "Review the expanded genomic-screening guidance against local practice.",
        ],
    }

    def _kb_mock() -> MagicMock:
        kb = MagicMock()
        kb.list_entries.return_value = list(entries)
        return kb

    product_template = None
    if product == "premium-briefing":
        product_template = next(
            row["template"] for row in PRODUCT_TEMPLATES if row["name"] == product
        )

    with (
        patch("autoinfo.output.KBStore", return_value=_kb_mock()),
        patch("autoinfo.llm.LLMExtractor.extract", return_value=empty_extract),
        patch("autoinfo.output._call_llm_for_digest", return_value={}),
    ):
        if product == "digest":
            out = generate_digest(
                domain=domain,
                period=period,
                format="markdown",
                user_id=user_id,
            )
        else:
            with (
                patch("autoinfo.output._group_by_theme", return_value=group),
                patch(
                    "autoinfo.output._generate_executive_summary",
                    return_value=dict(synthesis),
                ),
                patch(
                    "autoinfo.output._call_llm_for_report_synthesis",
                    return_value="",
                ),
            ):
                out = generate_report(
                    domain=domain,
                    format="markdown",
                    user_id=user_id,
                    product_template=product_template,
                )

    if not isinstance(out, str) or not out.strip():
        raise ValueError(
            f"hermetic generation produced no output for product '{product}'"
        )
    product_path = user_dir / file_name
    product_path.write_text(out, encoding="utf-8")
    return product_path, entries


def _write_provenance(
    user_dir: Path,
    product_path: Path,
    entries: list[dict[str, Any]],
    *,
    product: str,
    domain: str,
    period: str,
    user_id: str,
    gate: dict[str, Any],
) -> Path:
    """Write ``provenance.json`` — per-entry source provenance + disclosure."""
    provenance = {
        "user_id": user_id,
        "domain": domain,
        "product": product,
        "period": period,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "hermetic-fixture",
        "hermetic": True,
        "llm_calls": 0,
        "seam": (
            "KBStore+LLM injection seam (autoinfo mvp init first-product "
            "seam; mirror of regression-no-placeholder-magazine-tutorial) — "
            "static fixture entries, deterministic synthesis, no network"
        ),
        "product_file": product_path.name,
        "entries": [
            {
                "title": e.get("title", ""),
                "source_url": e.get("source_url", ""),
                "source_type": e.get("source_type", ""),
                "source_platform": e.get("source_platform", ""),
                "collected_at": e.get("collected_at", ""),
            }
            for e in entries
        ],
        "gate_report": {
            "md": gate["md"].name,
            "json": gate["json"].name,
            "quality": gate["quality"],
        },
    }
    path = user_dir / "provenance.json"
    path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


# ---------------------------------------------------------------------------
# `mvp init`
# ---------------------------------------------------------------------------


@app.command()
def init(
    user: str = typer.Option(..., "--user", help="Pilot end-user ID"),
    domain: str = typer.Option(
        ..., "--domain", help="Demo domain to import (e.g. medical-research)"
    ),
    product: str = typer.Option(
        "digest",
        "--product",
        help="First product: digest, report, premium-briefing",
    ),
    frequency: str = typer.Option(
        "weekly", "--frequency", help="Delivery frequency: daily, weekly"
    ),
) -> None:
    """Provision a Concierge MVP pilot end-to-end (idempotent).

    Creates the premium end-user profile + subscription (no Stripe), imports
    the demo domain config, generates the first product via the hermetic
    seam, and writes the ``mvp/<user>/`` delivery directory (product + gate
    report + provenance + user.json).
    """
    if product not in _VALID_PRODUCTS:
        typer.echo(
            f"Error: Unknown product '{product}'. "
            f"Valid products: {', '.join(_VALID_PRODUCTS)}",
            err=True,
        )
        raise typer.Exit(code=1)
    if frequency not in _VALID_FREQUENCIES:
        typer.echo(
            f"Error: Unknown frequency '{frequency}'. "
            f"Valid frequencies: {', '.join(_VALID_FREQUENCIES)}",
            err=True,
        )
        raise typer.Exit(code=1)
    if not user or "/" in user or "\\" in user or user in (".", ".."):
        typer.echo(
            f"Error: invalid user id {user!r} — must be a non-empty path-safe "
            f"identifier (no slashes)",
            err=True,
        )
        raise typer.Exit(code=1)

    if get_config_path() is None:
        typer.echo(_NO_CONFIG_ERROR, err=True)
        raise typer.Exit(code=1)

    # --- (1) Domain import FIRST (clean early error before any user writes).
    # Reuses domain.py import_cmd verbatim — the --from-demo source of truth.
    from autoinfo.cli.domain import import_cmd as _import_demo_domain  # noqa: PLC0415
    from autoinfo.user_store import (  # noqa: PLC0415
        create_profile,
        create_subscription,
        get_profile,
        list_subscriptions,
    )

    _import_demo_domain(from_demo=domain)

    # --- (2) EndUserProfile — premium fast-path mechanism -------------------
    profile = get_profile(user)
    if profile is None:
        create_profile(
            user_id=user,
            name=user,
            email="",
            status="active",
            tier="premium",
        )
        typer.echo(f"Profile '{user}' created (tier=premium, status=active).")
    else:
        typer.echo(
            f"Profile '{user}' already exists "
            f"(tier={profile.tier}, status={profile.status}) — skipping."
        )

    # --- (3) Premium subscription (no Stripe) -------------------------------
    sub = next(
        (
            s
            for s in list_subscriptions(user)
            if s.plan == "premium" and s.tier == "premium"
        ),
        None,
    )
    if sub is None:
        sub = create_subscription(
            user_id=user,
            plan="premium",
            status="active",
            tier="premium",
            auto_renew=True,
            channels=[],
            domains=[domain],
            products=[product],
            platform_limit=8,
            domain_limit=8,
            raw_access=False,
            processed_access=True,
            max_products=8,
            max_frequency="daily",
            allow_custom=True,
        )
        typer.echo(
            f"Subscription created: {sub.subscription_id} "
            f"(plan=premium, tier=premium, status=active)."
        )
    else:
        typer.echo(
            f"Subscription already exists ({sub.subscription_id}, "
            f"plan=premium) — skipping."
        )

    # --- (4) First product via the hermetic seam ----------------------------
    user_dir = Path.cwd() / "mvp" / user
    existing_products = (
        _existing_product_files(user_dir) if user_dir.is_dir() else []
    )

    if existing_products:
        typer.echo(
            f"Pilot '{user}' already has a first product "
            f"({existing_products[-1].name}) — generation skipped."
        )
    else:
        user_dir.mkdir(parents=True, exist_ok=True)
        try:
            product_path, entries = _generate_first_product(
                product=product,
                domain=domain,
                period=frequency,
                user_id=user,
                user_dir=user_dir,
            )
        except Exception as exc:  # noqa: BLE001 — clean CLI error, no traceback
            typer.echo(
                f"Error: first product generation failed: {exc}", err=True
            )
            raise typer.Exit(code=1) from exc

        from autoinfo.delivery.gate_report import write_gate_report  # noqa: PLC0415

        # Cwd-relative product path (mirrors validation_delivery's
        # relativized artifact paths, #143) so the report key never embeds
        # an absolute mount/user prefix.
        try:
            key_path = product_path.relative_to(Path.cwd())
        except ValueError:
            key_path = product_path
        gate = write_gate_report(user_dir, key_path, kind="PROCESSED")
        _write_provenance(
            user_dir,
            product_path,
            entries,
            product=product,
            domain=domain,
            period=frequency,
            user_id=user,
            gate=gate,
        )
        typer.echo(
            f"First product generated: {product_path.as_posix()} "
            f"(gate: {gate['quality']}, hermetic seam: no LLM call)."
        )

    # --- (5) user.json placeholder metadata ---------------------------------
    meta_path = user_dir / "user.json"
    meta = {
        "user_id": user,
        "name": user,
        "email": "",
        "domain": domain,
        "product": product,
        "frequency": frequency,
        "tier": "premium",
        "plan": "premium",
        "status": "active",
        "subscription_id": sub.subscription_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mvp_dir": user_dir.as_posix(),
        "placeholder": True,
    }
    meta_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    typer.echo(
        f"MVP pilot ready: {user_dir.as_posix()} (user={user}, domain={domain}, "
        f"product={product}, frequency={frequency})"
    )


# ---------------------------------------------------------------------------
# `mvp list`
# ---------------------------------------------------------------------------


@app.command(name="list")
def list_cmd() -> None:
    """List MVP pilot users with subscription status and latest product."""
    from autoinfo.user_store import get_profile, list_subscriptions  # noqa: PLC0415

    base = Path.cwd() / "mvp"
    pilots: list[tuple[Path, dict[str, Any]]] = []
    if base.is_dir():
        for d in sorted(base.iterdir()):
            meta_path = d / "user.json"
            if d.is_dir() and meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    meta = {}
                if isinstance(meta, dict):
                    pilots.append((d, meta))

    if not pilots:
        typer.echo(
            "No MVP pilot users yet. Run 'autoinfo mvp init --user <id> "
            "--domain <domain>' to provision one."
        )
        return

    typer.echo(f"MVP pilot users ({len(pilots)}):")
    for d, meta in pilots:
        uid = str(meta.get("user_id") or d.name)
        profile = get_profile(uid)
        tier = (profile.tier if profile else None) or str(meta.get("tier", "?"))
        status = (profile.status if profile else None) or str(
            meta.get("status", "?")
        )
        subs = list_subscriptions(uid)
        plan = subs[0].plan if subs else str(meta.get("plan", "?"))
        sub_status = subs[0].status if subs else "?"
        products = _existing_product_files(d)
        latest = (
            max(products, key=lambda p: p.stat().st_mtime) if products else None
        )
        latest_rel = latest.as_posix() if latest else "none"
        typer.echo(
            f"  {uid}: tier={tier} plan={plan} status={status} "
            f"subscription={sub_status} "
            f"product={meta.get('product', '?')} "
            f"frequency={meta.get('frequency', '?')}"
        )
        typer.echo(f"      latest product: {latest_rel}")


if __name__ == "__main__":
    app()
