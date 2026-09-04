"""Storefront router — end-user product catalog & subscription creation.

Serves a Bootstrap 5 web UI at ``/storefront`` that lets end users browse
the product catalog (derived from configured domains) and create
subscriptions.  Mirrors the styling of the existing ``/portal`` and
``/dashboard`` routes.

No authentication — localhost security zone (same as the existing REST
API).  Freemium gating is enforced via :func:`autoinfo.billing.check_access`
(G15) on the product detail page.

Routes
------
- ``GET  /storefront``                       — landing → redirect to catalog
- ``GET  /storefront/products``             — product catalog (HTML / JSON)
- ``GET  /storefront/products/{product_id}`` — product detail (HTML / JSON)
- ``POST /storefront/subscriptions``        — create subscription (JSON)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from autoinfo.api.routes import success_envelope

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Templates (module-level singleton — directory is fixed)
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates" / "storefront"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["storefront"])

# ---------------------------------------------------------------------------
# Pricing & tier mapping
# ---------------------------------------------------------------------------

# Product type → (access_level, default monthly price, currency).
# RAW feeds are free-tier (API access); PROCESSED outputs are premium.
# Prices here are placeholders pending a pricing decision.
_PRODUCT_PRICING: dict[str, dict[str, Any]] = {
    "raw": {
        "access_level": "free",
        "price_monthly": 0.0,
        "currency": "USD",
        "tier": "free",
    },
    "processed": {
        "access_level": "premium",
        "price_monthly": 29.0,
        "currency": "USD",
        "tier": "premium",
    },
}


def _tier_badge_class(tier: str) -> str:
    """Return a Bootstrap 5 badge class for a subscription tier."""
    return {
        "free": "text-bg-secondary",
        "premium": "text-bg-primary",
        "enterprise": "text-bg-warning",
    }.get(tier, "text-bg-light")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_cfg() -> Any:
    """Load the AutoInfo config (deferred import to avoid circular deps)."""
    from autoinfo.config import load_config

    config_path = Path.cwd() / ".autoinfo" / "config.yaml"
    return load_config(config_path)


def _list_all_products() -> list[dict[str, Any]]:
    """Return all configured products across every domain with pricing/tier.

    Aggregates the MCP backend's ``_handle_list_products`` for each
    configured domain, then enriches each product with access level,
    monthly price, and currency from :data:`_PRODUCT_PRICING`.
    Returns an empty list when no domains are configured or the config
    cannot be loaded.
    """
    try:
        from autoinfo.mcp.server import _handle_list_products

        cfg = _load_cfg()
    except Exception:  # pragma: no cover — defensive
        logger.debug("Could not load config for storefront listing", exc_info=True)
        return []

    products: list[dict[str, Any]] = []
    for domain in getattr(cfg, "domains", []) or []:
        name = getattr(domain, "name", "")
        if not name:
            continue
        result = _handle_list_products(domain=name)
        if "error_code" in result:
            continue
        for product in result.get("products", []):
            ptype = (product.get("type") or "").lower()
            pricing = _PRODUCT_PRICING.get(ptype, _PRODUCT_PRICING["raw"])
            enriched = dict(product)
            enriched.update(
                {
                    "access_level": pricing["access_level"],
                    "price_monthly": pricing["price_monthly"],
                    "currency": pricing["currency"],
                    "tier": pricing["tier"],
                }
            )
            products.append(enriched)
    return products


def _get_product(product_id: str) -> dict[str, Any] | None:
    """Return a single product by id, or ``None`` if not found.

    Iterates over all configured domains and product types (RAW,
    PROCESSED) using the MCP backend's ``_handle_get_product``.
    Enriches the result with pricing/tier metadata.
    """
    try:
        from autoinfo.mcp.server import _handle_get_product

        cfg = _load_cfg()
    except Exception:  # pragma: no cover — defensive
        logger.debug("Could not load config for storefront detail", exc_info=True)
        return None

    for domain in getattr(cfg, "domains", []) or []:
        name = getattr(domain, "name", "")
        if not name:
            continue
        for ptype in ("RAW", "PROCESSED"):
            result = _handle_get_product(domain=name, product_type=ptype)
            if "error_code" in result:
                continue
            product = result.get("product") or {}
            if (product.get("id") or "") == product_id:
                ptype_lower = (product.get("type") or "").lower()
                pricing = _PRODUCT_PRICING.get(
                    ptype_lower, _PRODUCT_PRICING["raw"]
                )
                enriched = dict(product)
                enriched.update(
                    {
                        "access_level": pricing["access_level"],
                        "price_monthly": pricing["price_monthly"],
                        "currency": pricing["currency"],
                        "tier": pricing["tier"],
                    }
                )
                return enriched
    return None


def _render_error(
    request: Request, message: str, status_code: int = 404
) -> HTMLResponse:
    """Render the storefront error page."""
    return templates.TemplateResponse(
        request,
        "error.html",
        {"error_message": message},
        status_code=status_code,
    )


def _error_envelope_json(
    status_code: int,
    code: str,
    message: str,
    actionable: bool = True,
) -> JSONResponse:
    """Build a JSONResponse with the canonical error envelope."""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {"code": code, "message": message, "actionable": actionable},
        },
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class SubscriptionCreate(BaseModel):
    """Request body for ``POST /storefront/subscriptions``."""

    user_id: str = Field(..., min_length=1, description="End-user identifier")
    product_id: str = Field(
        ..., min_length=1, description="Product id (e.g. 'medical-research-processed')"
    )
    plan: str = Field("free", description="Subscription plan name")
    tier: str = Field("free", description="Subscription tier (free/premium/enterprise)")
    auto_renew: bool = Field(True, description="Auto-renew at period end")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/storefront", response_class=HTMLResponse)
async def storefront_root() -> RedirectResponse:
    """Redirect ``/storefront`` → ``/storefront/products``."""
    return RedirectResponse(url="/storefront/products", status_code=302)


@router.get("/storefront/products", response_class=HTMLResponse, response_model=None)
async def product_catalog(
    request: Request,
    format: str = Query(
        "html", description="Response format: 'html' (default) or 'json'"
    ),
) -> HTMLResponse | JSONResponse:
    """Product catalog — list all products with pricing and tier badges.

    Query params:
        format: ``html`` (default) renders the Bootstrap catalog page;
        ``json`` returns a structured JSON payload.
    """
    products = _list_all_products()

    if format.lower() == "json":
        return JSONResponse(
            content=jsonable_encoder(
                success_envelope(
                    {
                        "products": products,
                        "count": len(products),
                    }
                )
            )
        )

    context = {
        "products": products,
        "product_count": len(products),
        "tier_badge_class": _tier_badge_class,
    }
    return templates.TemplateResponse(request, "catalog.html", context)


@router.get(
    "/storefront/products/{product_id}",
    response_class=HTMLResponse,
    response_model=None,
)
async def product_detail(
    product_id: str,
    request: Request,
    user_id: str = Query(
        "", description="Optional end-user id for access gating"
    ),
    format: str = Query(
        "html", description="Response format: 'html' (default) or 'json'"
    ),
) -> HTMLResponse | JSONResponse:
    """Product detail page with pricing, tier, and subscribe CTA.

    When ``user_id`` is provided, runs :func:`autoinfo.billing.check_access`
    to determine whether the user can subscribe to / access the product.
    """
    product = _get_product(product_id)
    if product is None:
        if format.lower() == "json":
            return _error_envelope_json(
                status_code=404,
                code="NotFound",
                message=f"Product '{product_id}' not found",
            )
        return _render_error(
            request, f"Product '{product_id}' not found.", status_code=404
        )

    # Freemium gating (G15) — only when a user_id is supplied
    access: dict[str, Any] = {
        "allowed": True,
        "reason": "",
        "upgrade_prompt": None,
    }
    if user_id:
        try:
            from autoinfo.billing import check_access

            access = check_access(
                end_user_id=user_id,
                access_level=product.get("access_level", "free"),
            )
        except Exception:  # pragma: no cover — defensive
            logger.debug("check_access failed, defaulting to allowed", exc_info=True)
            access = {
                "allowed": True,
                "reason": "Access check unavailable — defaulting to allowed.",
                "upgrade_prompt": None,
            }

    if format.lower() == "json":
        return JSONResponse(
            content=jsonable_encoder(
                success_envelope(
                    {
                        "product": product,
                        "access": access,
                    }
                )
            )
        )

    context = {
        "product": product,
        "access": access,
        "user_id": user_id,
        "tier_badge_class": _tier_badge_class,
    }
    return templates.TemplateResponse(request, "product.html", context)


@router.post("/storefront/subscriptions")
async def create_subscription(
    body: SubscriptionCreate,
) -> JSONResponse:
    """Create a new subscription for an end user.

    Validates that the referenced product exists, then delegates to
    :func:`autoinfo.user_store.create_subscription`.  No payment is
    processed here — Stripe checkout is handled separately via the
    existing billing endpoints.
    """
    product = _get_product(body.product_id)
    if product is None:
        return _error_envelope_json(
            status_code=404,
            code="NotFound",
            message=f"Product '{body.product_id}' not found",
        )

    # Derive subscription parameters from the product
    domain = product.get("domain", "")
    ptype = (product.get("type") or "").lower()
    raw_access = ptype == "raw"
    processed_access = ptype == "processed"
    tier = body.tier or product.get("tier", "free")

    try:
        from autoinfo.user_store import create_subscription as _create_sub

        sub = _create_sub(
            user_id=body.user_id,
            plan=body.plan or body.product_id,
            status="active",
            tier=tier,
            auto_renew=body.auto_renew,
            domains=[domain] if domain else [],
            products=[body.product_id],
            raw_access=raw_access,
            processed_access=processed_access,
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("Subscription creation failed: %s", exc, exc_info=True)
        return _error_envelope_json(
            status_code=500,
            code="InternalError",
            message=f"Failed to create subscription: {exc}",
            actionable=False,
        )

    return JSONResponse(
        status_code=201,
        content=jsonable_encoder(
            success_envelope(
                {
                    "subscription_id": sub.subscription_id,
                    "user_id": sub.user_id,
                    "product_id": body.product_id,
                    "plan": sub.plan,
                    "tier": sub.tier,
                    "status": sub.status,
                    "auto_renew": sub.auto_renew,
                }
            )
        ),
    )
