"""REST API server — exposes AutoInfo capabilities over HTTP.

Usage::

    python -m autoinfo.api.server

The server listens on ``http://127.0.0.1:8741`` by default.
Port and host are configurable via ``.autoinfo/config.yaml`` under the
``rest_api`` key.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse

from autoinfo import __version__
from autoinfo.api.portal import router as portal_router
from autoinfo.api.routes import router as api_v1_router
from autoinfo.api.storefront import router as storefront_router
from autoinfo.config import RestAPIConfig
from autoinfo.mcp.errors import ErrorCode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config I/O (mirrors mcp/server.py pattern)
# ---------------------------------------------------------------------------


def _config_path() -> Path:
    """Return the path to the project's ``.autoinfo/config.yaml``."""
    return Path.cwd() / ".autoinfo" / "config.yaml"


def _load_rest_config() -> RestAPIConfig:
    """Load REST API config from ``.autoinfo/config.yaml``.

    Looks for a ``rest_api`` section with ``port`` and ``host`` keys.
    When the config file is absent or the section is missing, falls back
    to defaults (127.0.0.1:8741).

    Once Task 3 adds ``rest_api`` to the :class:`Config` dataclass, the
    ``getattr`` path below will return the parsed ``RestAPIConfig``
    directly from YAML.
    """
    config_path = _config_path()
    if not config_path.is_file():
        logger.info("No config found at %s, using defaults", config_path)
        return RestAPIConfig()

    # Try the structured Config object first (Task 3+)
    try:
        from autoinfo.config import load_config

        config = load_config(config_path)
        rest_api: Any = getattr(config, "rest_api", None)
        if rest_api is not None and isinstance(rest_api, RestAPIConfig):
            return rest_api
    except Exception:
        logger.debug("Could not load rest_api from Config object", exc_info=True)

    # Fall back to reading raw YAML
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}
        rest_api_raw: dict[str, Any] = raw.get("rest_api", {}) or {}
        return RestAPIConfig(
            port=int(rest_api_raw.get("port", 8741)),
            host=str(rest_api_raw.get("host", "127.0.0.1")),
        )
    except Exception:
        logger.warning("Failed to parse rest_api config, using defaults", exc_info=True)
        return RestAPIConfig()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

_server_start_time: float = time.time()

app = FastAPI(title="AutoInfo API", version=__version__)

# -- CORS: allow all origins (localhost security zone) ------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Domain validation helper — shared between middleware and routes
# ---------------------------------------------------------------------------


def _known_domains() -> set[str]:
    """Return the set of known domain names.

    Checks configured domains in ``.autoinfo/config.yaml`` first,
    then falls back to scanning the ``knowledge/`` directory for
    directories that represent domain namespaces.
    """
    domains: set[str] = set()

    # -- From config -----------------------------------------------------------
    try:
        from autoinfo.config import get_config_path, load_config

        config_path = get_config_path()
        if config_path and config_path.is_file():
            config = load_config(config_path)
            for d in config.domains:
                domains.add(d.name)
    except Exception:
        logger.debug("Could not load domains from config", exc_info=True)

    # -- From filesystem (fallback) -------------------------------------------
    kb_dir = Path("knowledge")
    if kb_dir.is_dir():
        for entry in kb_dir.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                domains.add(entry.name)

    return domains


# ---------------------------------------------------------------------------
# HTTP middleware — domain precondition check for domain-specific routes
# ---------------------------------------------------------------------------


@app.middleware("http")
async def domain_validation_middleware(request: Request, call_next):
    """Validate that the ``domain`` query parameter refers to an existing domain.

    Only applies to ``/api/v1/*`` GET and DELETE routes that accept a
    ``domain`` query parameter.  Returns ``404 DOMAIN_NOT_FOUND`` when
    a domain value is provided but not recognised.

    POST routes handle domain validation inline (the middleware cannot
    safely read the request body).
    """
    path = request.url.path
    if request.method in ("GET", "DELETE") and path.startswith("/api/v1/"):
        domain = request.query_params.get("domain", "").strip()
        if domain:
            known = _known_domains()
            if domain not in known:
                return _error_envelope(
                    status_code=404,
                    error_code=ErrorCode.DOMAIN_NOT_FOUND,
                    message=f"Domain '{domain}' not found. Use add_domain(name='{domain}') to create it.",
                )

    return await call_next(request)


# ---------------------------------------------------------------------------
# Exception handlers — canonical {success, error: {code, message}} envelope
# ---------------------------------------------------------------------------


def _error_envelope(
    status_code: int,
    error_code: str | ErrorCode,
    message: str,
    actionable: bool = True,
) -> JSONResponse:
    """Build a JSONResponse with the canonical error envelope."""
    code_str = error_code.value if isinstance(error_code, ErrorCode) else error_code
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "error": {
                "code": code_str,
                "message": message,
                "actionable": actionable,
            },
        },
    )


def _success_envelope(data: Any) -> dict[str, Any]:
    """Build the canonical success envelope ``{success: True, data: ...}``.

    Mirrors :func:`autoinfo.mcp.errors.success_response` — the REST-side
    counterpart of the MCP envelope.  Pairs with :func:`_error_envelope`
    which returns the error counterpart.  ``/health`` is the single
    documented exemption (flat ops probe, mirrors MCP ``health_check``).
    """
    return {"success": True, "data": data}


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Map FastAPI ``RequestValidationError`` → 422 with canonical envelope.

    FastAPI's default 422 body is a bare ``{detail: [...]}`` list; the M1
    contract requires every REST error to carry the canonical
    ``{success: False, error: {code, message, actionable}}`` envelope.
    The first validation error is summarized into a readable message
    (e.g. ``body.title: Field required``).
    """
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = ".".join(str(part) for part in first.get("loc", []))
    msg = str(first.get("msg", "Request validation failed"))
    message = f"{loc}: {msg}" if loc else msg
    logger.warning(
        "RequestValidationError in %s %s (422): %s",
        request.method,
        request.url.path,
        message,
    )
    return _error_envelope(
        status_code=422,
        error_code=ErrorCode.VALIDATION_ERROR,
        message=message,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request, exc: HTTPException
) -> JSONResponse:
    """Map FastAPI HTTPException → same status with canonical envelope."""
    code = (
        ErrorCode.VALIDATION_ERROR
        if 400 <= exc.status_code < 500
        else ErrorCode.INTERNAL_ERROR
    )
    logger.warning(
        "HTTPException in %s %s (%d): %s",
        request.method,
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    return _error_envelope(
        status_code=exc.status_code,
        error_code=code,
        message=str(exc.detail),
        actionable=exc.status_code < 500,
    )


@app.exception_handler(ValueError)
async def value_error_handler(
    request: Request, exc: ValueError
) -> JSONResponse:
    """Map ValueError → 400 Bad Request."""
    logger.warning(
        "ValueError in %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    return _error_envelope(
        status_code=400,
        error_code=ErrorCode.VALIDATION_ERROR,
        message=str(exc),
    )


@app.exception_handler(KeyError)
async def key_error_handler(
    request: Request, exc: KeyError
) -> JSONResponse:
    """Map KeyError → 400 Bad Request."""
    logger.warning(
        "KeyError in %s %s: %s",
        request.method,
        request.url.path,
        exc,
    )
    return _error_envelope(
        status_code=400,
        error_code=ErrorCode.VALIDATION_ERROR,
        message=str(exc),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for all unhandled exceptions → 500."""
    logger.error(
        "Unhandled exception in %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return _error_envelope(
        status_code=500,
        error_code=ErrorCode.INTERNAL_ERROR,
        message=str(exc) if str(exc) else "An unhandled server error occurred.",
        actionable=False,
    )


# ---------------------------------------------------------------------------
# API v1 Router
# ---------------------------------------------------------------------------

app.include_router(api_v1_router, prefix="/api/v1")

# ---------------------------------------------------------------------------
# Portal router — read-only end-user dashboard (Jinja2 + Bootstrap 5)
# ---------------------------------------------------------------------------

app.include_router(portal_router)

# ---------------------------------------------------------------------------
# Storefront router — end-user product catalog & subscription creation
# ---------------------------------------------------------------------------

app.include_router(storefront_router)

# ---------------------------------------------------------------------------
# Dashboard (read-only web UI)
# ---------------------------------------------------------------------------

_DASHBOARD_HTML_PATH = Path(__file__).resolve().parent / "dashboard.html"


def _load_dashboard_html() -> str:
    """Read the dashboard HTML file from disk (cached per-process)."""
    global _dashboard_html_cache
    if _dashboard_html_cache is None:
        if _DASHBOARD_HTML_PATH.is_file():
            _dashboard_html_cache = _DASHBOARD_HTML_PATH.read_text(encoding="utf-8")
        else:
            _dashboard_html_cache = (
                "<!doctype html><html><body>"
                "<h1>AutoInfo Dashboard</h1>"
                "<p>dashboard.html not found at "
                f"{_DASHBOARD_HTML_PATH}</p>"
                "</body></html>"
            )
    return _dashboard_html_cache


_dashboard_html_cache: str | None = None


@app.get("/", response_class=HTMLResponse)
async def dashboard_root() -> str:
    """Serve the read-only dashboard at the site root."""
    return _load_dashboard_html()


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> str:
    """Serve the read-only dashboard at ``/dashboard``."""
    return _load_dashboard_html()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, Any]:
    """Quick status ping — returns version and server uptime."""
    return {
        "status": "ok",
        "version": __version__,
        "uptime_s": round(time.time() - _server_start_time, 2),
    }


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics() -> str:
    """Prometheus-format metrics for scraping."""
    from autoinfo.metrics import format_prometheus, get_metrics

    data = get_metrics()
    return format_prometheus(data)


# ---------------------------------------------------------------------------
# Media serving — podcast MP3 hosting
# ---------------------------------------------------------------------------

# Allowed root directories for media file serving (security: prevent
# path traversal outside these directories).
_MEDIA_ROOTS: tuple[Path, ...] = (
    Path("exports"),
    Path("data"),
)


@app.get("/media/{file_path:path}")
async def serve_media(file_path: str) -> FileResponse:
    """Serve a static media file (e.g. podcast MP3) from ``exports/`` or ``data/``.

    Security: only serves files from allowed media root directories.
    Returns 404 when the path escapes the allowed roots or the file
    does not exist.
    """
    cwd = Path.cwd().resolve()
    resolved_abs = (cwd / file_path).resolve()

    allowed = False
    for media_root in _MEDIA_ROOTS:
        try:
            root_abs = (cwd / media_root).resolve()
            if str(resolved_abs).startswith(str(root_abs) + os.sep) or resolved_abs == root_abs:
                if resolved_abs.is_file():
                    allowed = True
                    break
        except (ValueError, OSError):
            continue

    if not allowed:
        raise HTTPException(
            status_code=404,
            detail=f"Media file not found: {file_path}",
        )

    return FileResponse(
        path=str(resolved_abs),
        media_type="audio/mpeg",
        headers={"Accept-Ranges": "bytes"},
    )


# ---------------------------------------------------------------------------
# Stripe webhook endpoint
# ---------------------------------------------------------------------------


@app.post("/api/v1/webhook/stripe")
async def stripe_webhook(request: Request) -> JSONResponse:
    """Accept Stripe webhook events with signature verification.

    Verifies the webhook signature using ``stripe.Webhook.construct_event``.
    When ``STRIPE_WEBHOOK_SECRET`` is not configured, verification is
    skipped and a warning is logged (dev/stripe-mock mode).

    Returns a ``JSONResponse`` on invalid signature (400) or the result
    dict from :func:`autoinfo.billing.handle_webhook` on success.
    """
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature", "")

    # --- Resolve webhook secret ------------------------------------------------
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not webhook_secret:
        # Try config file as fallback
        try:
            from autoinfo.config import get_config_path, load_config

            config_path = get_config_path()
            if config_path:
                cfg = load_config(config_path)
                webhook_secret = cfg.stripe.webhook_secret
        except Exception:
            logger.debug(
                "Could not load stripe.webhook_secret from config", exc_info=True,
            )

    # --- Signature verification ------------------------------------------------
    if webhook_secret:
        try:
            import stripe

            event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
        except ValueError as exc:
            logger.warning("Stripe webhook: invalid payload: %s", exc)
            return _error_envelope(
                status_code=400,
                error_code=ErrorCode.VALIDATION_ERROR,
                message=f"invalid_signature: {exc}",
            )
        except stripe.error.SignatureVerificationError as exc:
            logger.warning("Stripe webhook: signature verification failed: %s", exc)
            return _error_envelope(
                status_code=400,
                error_code=ErrorCode.VALIDATION_ERROR,
                message=f"invalid_signature: {exc}",
            )
    else:
        # Dev mode: no secret configured — parse raw JSON
        logger.warning(
            "STRIPE_WEBHOOK_SECRET not set — "
            "skipping signature verification (dev mode)",
        )
        try:
            event = json.loads(payload)
        except json.JSONDecodeError as exc:
            return _error_envelope(
                status_code=400,
                error_code=ErrorCode.VALIDATION_ERROR,
                message=f"invalid_payload: {exc}",
            )

    # --- Dispatch to billing handler -------------------------------------------
    from autoinfo.billing import handle_webhook

    result = handle_webhook(dict(event))
    return JSONResponse(content=result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the REST API server via ``uvicorn.run()``."""
    cfg = _load_rest_config()
    logger.info(
        "Starting AutoInfo API on http://%s:%d",
        cfg.host,
        cfg.port,
    )
    uvicorn.run(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
