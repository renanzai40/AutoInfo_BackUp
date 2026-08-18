"""YAML-based configuration loading, validation, and command guard.

Provides dataclasses for project/LLM/domain configuration, YAML parsing
with env var resolution, validation, and the ``ensure_config_exists``
guard used by CLI commands.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Source type registry — single source of truth
# ---------------------------------------------------------------------------

# Every source type ``_build_handler`` can dispatch (``api`` covers PubMed and
# the generic HTTP API), plus ``webhook`` (inbound push, delivered via the
# webhook receiver, not ``_build_handler``) and six forward-declared types
# (T7-T10). Adding a type requires updating BOTH this set and ``_build_handler``
# — enforced by the parity test in ``tests/test_source_dispatch.py``.
VALID_SOURCE_TYPES: frozenset[str] = frozenset({
    "akshare",
    "api",
    "ap_api",
    "apple_podcasts",
    "bilibili",
    "core",
    "dblp",
    "edx_sitemap",
    "email",
    "email_imap",
    "gdelt",
    "hackernews",
    "huggingface",
    "kaggle",
    "nyt",
    "openalex",
    "pdf",
    "quandl",
    "reddit",
    "reuters_mcp",
    "rss",
    "sec_edgar",
    "spotify",
    "ssrn",
    "unpaywall",
    "web",
    "webhook",
    "yahoo_finance",
    "youtube",
})

# Source type -> env var names that supply its credential(s).  Single source
# of truth for source-key requirements (D4), consumed by ``alerts.py``
# (B3 credential-missing detection) and ``mcp/server.py`` (key status,
# ``init_project`` next_steps, ``add_source`` requires_key derivation).
# Union of the two historical maps (``alerts._SOURCE_KEY_ENV`` and
# ``mcp.server._SOURCE_KEY_REQUIREMENTS``): every collector whose
# ``requires_key()`` is True (ap_api, reuters_mcp, unpaywall, youtube) plus
# the collect-time key guards (nyt, spotify, quandl, kaggle, core) and the
# email/email_imap guards.  Values are env var NAMES — raw key values never
# appear here.
SOURCE_KEY_ENV_VARS: dict[str, tuple[str, ...]] = {
    "ap_api": ("AUTOINFO_AP_API_KEY",),
    "nyt": ("AUTOINFO_NYT_API_KEY",),
    "quandl": ("AUTOINFO_QUANDL_API_KEY",),
    "reuters_mcp": ("AUTOINFO_REUTERS_API_KEY",),
    "unpaywall": ("AUTOINFO_UNPAYWALL_EMAIL",),
    "youtube": ("AUTOINFO_YOUTUBE_API_KEY",),
    "spotify": ("AUTOINFO_SPOTIFY_CLIENT_ID", "AUTOINFO_SPOTIFY_CLIENT_SECRET"),
    "core": ("AUTOINFO_CORE_API_KEY",),
    "kaggle": ("KAGGLE_USERNAME", "KAGGLE_KEY"),
    "email": ("AUTOINFO_EMAIL_PASSWORD",),
    "email_imap": ("AUTOINFO_EMAIL_PASSWORD",),
}

# quality_tier -> tos_classification mapping (source of truth for
# ``SourceConfig.__post_init__`` tier auto-mapping and YAML parsing).
TIER_TOS_MAP: dict[int, str] = {
    1: "open",
    2: "licensed",
    3: "restricted",
    4: "sensitive",
}

# Top-level keys belonging to ``SourceConfig`` itself; everything else in a
# source dict is treated as custom ``settings``.
SOURCE_CORE_KEYS: frozenset[str] = frozenset({
    "name",
    "type",
    "url",
    "quality_tier",
    "tos_classification",
    "fetch_depth",
    "requires_key",
})

# Allowed ``action`` values for hard and soft quality gates.
HARD_GATE_ACTIONS: frozenset[str] = frozenset({"block", "retry"})
SOFT_GATE_ACTIONS: frozenset[str] = frozenset({"retry", "flag", "skip", "archive"})

# ---------------------------------------------------------------------------
# Per-task LLM routing (release-pinned, static — never a runtime classifier)
# ---------------------------------------------------------------------------

# Release-pinned judgment model for the G4 (factual consistency), G5
# (translation accuracy) and llm_judge (translation QA gate 5) call sites.
# The value is chosen per release; changing it is a release-level decision,
# never a runtime one — judgment calls must NOT drift with task config.
JUDGMENT_MODEL = "deepseek-v4-flash"

# Task names whose model ALWAYS resolves to :data:`JUDGMENT_MODEL`, regardless
# of any ``llm.tasks[<name>].model`` runtime drift.
JUDGMENT_TASKS: frozenset[str] = frozenset(
    {"g4_factual", "g5_translation", "llm_judge"}
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ProjectConfig:
    name: str = ""
    project_name: str = ""
    created_at: str = ""


@dataclass
class LLMConfig:
    provider: str = ""
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    json_mode: bool = False
    reasoning_model: bool = False
    # Seconds per litellm call; overrides litellm's 600s default (config.yaml ``llm.timeout``).
    timeout: float = 120.0
    # Tokens per litellm call; ``None`` keeps the historical 2000 default.
    # Task-level overrides land here via :func:`_resolve_task_llm_config`.
    max_tokens: int | None = None
    fallback: list[LLMConfig] = field(default_factory=list)
    tasks: dict[str, LLMTaskConfig] = field(default_factory=dict)

    def resolve_model(self, default_provider: str | None = None) -> str:
        """Return the fully-qualified model string for LiteLLM.

        ``model`` may already carry a provider prefix (e.g.
        ``openai/deepseek-v4-flash``) or be a bare model name (e.g.
        ``gpt-4``).  When bare, the provider is prepended.  This avoids
        double-prefixing (``openai/openai/...``) when callers configure a
        prefixed model while also passing ``provider``.

        *default_provider* supplies the provider prefix when ``self.provider``
        is empty — used by callers that inherit a provider from elsewhere
        (e.g. an empty-provider fallback entry inheriting the primary
        provider).  When omitted the historical ``'openrouter'`` fallback is
        kept, so the no-argument call is fully backward compatible.
        """
        model = self.model or ""
        if "/" in model or not model:
            return model
        provider = self.provider or default_provider or "openrouter"
        return f"{provider}/{model}"


@dataclass
class LLMTaskConfig:
    """Per-task LLM model override.

    Attributes match :class:`LLMConfig` fields that make sense to
    override per-task (model, provider, max_tokens).  An empty string
    means "inherit from the base LLMConfig".
    """

    model: str = ""
    provider: str = ""
    max_tokens: int = 0


@dataclass
class SourceConfig:
    name: str = ""
    type: str = "api"
    url: str = ""
    quality_tier: int = 1
    tos_classification: str = "open"
    fetch_depth: str = "abstract"
    requires_key: bool = False
    settings: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Auto-map ``tos_classification`` from ``quality_tier`` when not explicitly set.

        The heuristic: if the current value is ``"open"`` (the dataclass default)
        but the tier maps to something different, the caller did not provide an
        explicit value, so we derive from the tier.

        ``requires_key`` is also coerced to a bool so string YAML values such as
        ``"true"`` / ``"false"`` never leak through as truthy strings.
        """
        mapped = TIER_TOS_MAP.get(self.quality_tier, "open")
        if self.tos_classification == "open" and mapped != "open":
            self.tos_classification = mapped
        self.requires_key = _as_bool(self.requires_key)


@dataclass
class TopicConfig:
    name: str = ""
    keywords: list[str] = field(default_factory=list)
    group: str = ""
    relevance_threshold: int = 30


@dataclass
class DomainConfig:
    name: str = ""
    description: str = ""
    active: bool = True
    sources: list[SourceConfig] = field(default_factory=list)
    topics: list[TopicConfig] = field(default_factory=list)
    extract_fields: list[str] = field(default_factory=list)
    search_mode: str = "keyword"  # keyword | hybrid
    webhook_urls: list[str] = field(default_factory=list)
    quality_gates: dict[str, QualityGateConfig] = field(default_factory=dict)
    delivery_gates: dict[str, DeliveryGateConfig] = field(default_factory=dict)
    ttl_days: int = 90
    freshness_threshold: float = 0.5
    # Keyword auto-discovery (#179): defaults keep pre-#179 behavior.
    auto_keyword_discovery: bool = True
    max_auto_keywords: int = 100
    auto_keyword_min_length: int = 2

    def __post_init__(self) -> None:
        """Apply domain-specific TTL defaults for built-in demo domains."""
        domain_defaults = {
            "medical-research": 180,
            "ai-commercial": 30,
            "financial-intelligence": 7,
            "tech-ai-developer": 90,
            "language-learning": 365,
        }
        if self.name in domain_defaults and self.ttl_days == 90:
            # Only override when ttl_days is the global default (90),
            # preserving any explicitly configured value.
            self.ttl_days = domain_defaults[self.name]


@dataclass
class CEFRConfig:
    """CEFR (Common European Framework of Reference) classification settings."""
    enabled: bool = False
    languages: list[str] = field(default_factory=lambda: ["en", "zh", "ja"])
    model: str = ""


@dataclass
class EmailConfig:
    """Email notification / collection settings."""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    from_addr: str = ""
    to_addrs: list[str] = field(default_factory=list)
    enabled: bool = False


@dataclass
class QualityGateConfig:
    """Configuration for a single quality gate (G0-G5 or custom).

    Attributes match the YAML schema in ``founder-expectations.md`` §4.4.

    A domain may also configure the ``CurationGate`` entry (promotion
    admission): ``threshold`` is the shared G1/G3 bar (default 30) and
    ``enabled`` toggles the G4 factual re-check (default ``True``).  When
    the entry is absent, those defaults apply (see ``autoinfo.promotion``).
    """

    name: str = ""
    category: str = "soft"  # "hard" | "soft"
    retries: int = 0
    retry_models: list[str] = field(default_factory=list)
    action: str = "flag"  # hard: block | retry; soft: retry | flag | skip | archive
    threshold: float | None = None
    window_days: int = 0  # G2 dedup time window (0 = no window limit)
    source_score_map: dict[int, float] = field(default_factory=dict)
    # Optional G1 tier→score override. When non-empty, replaces the module-level
    # SOURCE_TIER_SCORE_MAP for this gate. Example: {1: 95, 2: 75, 3: 55, 4: 25}.
    enabled: bool = True


@dataclass
class DeliveryGateConfig:
    """Configuration for a delivery gate (D1-D3).

    Checked at product output time for PROCESSED products.
    """

    name: str = ""
    enabled: bool = True
    action_on_failure: str = "block"  # block | fallback | flag


@dataclass
class LLMRateConfig:
    """Per-model LLM token pricing."""
    input_per_1k: float = 0.0
    output_per_1k: float = 0.0


@dataclass
class ApiCallRateConfig:
    """Per-source-type API call pricing."""
    per_call: float = 0.0


@dataclass
class StorageRateConfig:
    """Storage pricing — per item + per MB."""
    per_item: float = 0.0
    per_mb: float = 0.0


@dataclass
class CostRatesConfig:
    """Cost rate configuration for LLM tokens, API calls, and storage.

    Used by :class:`autoinfo.cost.CostMeter` to compute estimated costs.
    """

    llm: dict[str, LLMRateConfig] = field(default_factory=dict)
    api_calls: dict[str, ApiCallRateConfig] = field(default_factory=dict)
    storage: StorageRateConfig = field(default_factory=StorageRateConfig)

    @classmethod
    def defaults(cls) -> CostRatesConfig:
        """Return a :class:`CostRatesConfig` with sensible default rates."""
        return cls(
            llm={
                "deepseek/deepseek-chat": LLMRateConfig(
                    input_per_1k=0.00015, output_per_1k=0.00060
                ),
                "gpt-4o-mini": LLMRateConfig(
                    input_per_1k=0.00015, output_per_1k=0.00060
                ),
            },
            api_calls={
                "pubmed": ApiCallRateConfig(per_call=0.005),
                "rss": ApiCallRateConfig(per_call=0.001),
                "web": ApiCallRateConfig(per_call=0.002),
            },
            storage=StorageRateConfig(per_item=0.001, per_mb=0.01),
        )


@dataclass
class CostAlertsConfig:
    """Budget alert thresholds and auto-remediation configuration.

    Attributes
    ----------
    budget_thresholds:
        Percentage thresholds (0-100+) at which budget alerts fire.
        Defaults to ``[50.0, 75.0, 90.0, 100.0]``.
    auto_remediation_enabled:
        Whether auto-remediation is active (V2 — not implemented).
    alert_webhook:
        Optional webhook URL for budget alert notifications.
    """

    budget_thresholds: list[float] = field(default_factory=lambda: [50.0, 75.0, 90.0, 100.0])
    auto_remediation_enabled: bool = False
    alert_webhook: str = ""


@dataclass
class RestAPIConfig:
    """REST API server settings."""
    enabled: bool = True
    port: int = 8741
    host: str = "127.0.0.1"


@dataclass
class StripeConfig:
    """Stripe integration settings."""
    webhook_secret: str = ""


@dataclass
class VectorSearchConfig:
    """Vector / hybrid search settings (FTS5 + embeddings)."""
    enabled: bool = False
    model: str = ""
    hybrid_weight_fts5: float = 0.7
    hybrid_weight_vector: float = 0.3


@dataclass
class CronConfig:
    """Scheduled task (cron) settings."""
    auto_install: bool = False
    install_path: str = ""


@dataclass
class MultiUserConfig:
    """Multi-user / multi-tenant settings."""
    enabled: bool = False
    default_user_id: str = "default"


@dataclass
class OutputConfig:
    """Output generation settings.

    Attributes
    ----------
    pdf_timeout:
        Maximum seconds to allow for a single weasyprint PDF render
        (default 120).  Large knowledge bases may exceed this on slow
        machines — raise it via ``output.pdf_timeout`` in config.yaml.
    source_tier_badge:
        When True (default), digest and report templates render a
        ``[curated]`` / ``[fresh]`` badge per entry based on its
        ``source_tier`` (03-Wiki vs 02-Draft).  Disable via
        ``output.source_tier_badge: false`` in config.yaml.
    """

    pdf_timeout: float = 120.0
    source_tier_badge: bool = True


@dataclass
class TTSConfig:
    """Text-to-Speech engine settings.

    Attributes
    ----------
    engine:
        TTS engine to use. ``"local"`` (default, edge-tts, free and
        works where api.openai.com is unreachable — #210),
        ``"openai"`` for OpenAI TTS API,
        ``"whisper"`` for OpenAI Whisper model via TTS API.
    local_voice:
        Voice for the local engine (edge-tts).  See
        https://github.com/rany2/edge-tts#voices-list
        for available voices.  Defaults to ``"en-US-JennyNeural"``.
    """
    engine: str = "local"
    local_voice: str = "en-US-JennyNeural"


@dataclass
class Config:
    project: ProjectConfig = field(default_factory=ProjectConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    domains: list[DomainConfig] = field(default_factory=list)
    cefr: CEFRConfig = field(default_factory=CEFRConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    rest_api: RestAPIConfig = field(default_factory=RestAPIConfig)
    stripe: StripeConfig = field(default_factory=StripeConfig)
    vector_search: VectorSearchConfig = field(default_factory=VectorSearchConfig)
    cron: CronConfig = field(default_factory=CronConfig)
    multi_user: MultiUserConfig = field(default_factory=MultiUserConfig)
    quality_gates: dict[str, QualityGateConfig] = field(default_factory=dict)
    delivery_gates: dict[str, DeliveryGateConfig] = field(default_factory=dict)
    cost_rates: CostRatesConfig = field(default_factory=CostRatesConfig)
    cost_alerts: CostAlertsConfig = field(default_factory=CostAlertsConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    output: OutputConfig = field(default_factory=OutputConfig)


# ---------------------------------------------------------------------------
# Env var resolution
# ---------------------------------------------------------------------------

_ENV_VAR_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _as_bool(value: Any) -> bool:
    """Coerce a YAML-ish value to a bool, tolerating strings.

    PyYAML already parses ``true``/``false`` as Python bools, but a value
    written as a quoted string (``"true"``) or an integer (``1``) would
    otherwise be truthy in surprising ways.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _resolve_env_vars(value: str) -> str:
    """Replace ``${VAR_NAME}`` placeholders with environment variable values."""
    def _replace(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")
    return _ENV_VAR_PATTERN.sub(_replace, value)


def _resolve_env_vars_recursively(obj: Any) -> Any:
    """Walk an object tree and resolve env vars in all string fields."""
    if isinstance(obj, str):
        return _resolve_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars_recursively(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars_recursively(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

# Short quality-gate keys (used by the default config and older YAML files)
# mapped to the canonical long keys the pipeline looks up (e.g. process.py,
# quality.py).  ``G1-TosCompliance`` is already the long form and passes
# through unchanged.
_GATE_CONFIG_KEY_MAP: dict[str, str] = {
    "G0": "G0-SchemaIntegrity",
    "G1": "G1-SourceAuthority",
    "G1-TosCompliance": "G1-TosCompliance",
    "G2": "G2-Dedup",
    "G3": "G3-RelevanceScoring",
    "G4": "G4-SummaryFactual",
    "G5": "G5-TranslationAccuracy",
}


def _normalize_gate_config_keys(raw: dict[str, Any]) -> dict[str, Any]:
    """Map short quality-gate keys to their canonical long form.

    Accepts a dict whose keys are either short (``"G0"``) or long
    (``"G0-SchemaIntegrity"``) gate identifiers.  Short keys are rewritten to
    the long form the pipeline looks up; long keys pass through unchanged.
    When both forms appear for the same gate, the long key wins.
    """
    normalized: dict[str, Any] = {}
    for key, value in raw.items():
        normalized[_GATE_CONFIG_KEY_MAP.get(str(key), str(key))] = value
    return normalized


def load_config(path: Path | str) -> Config:
    """Parse *path* as YAML and return a :class:`Config` instance.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    yaml.YAMLError
        If the YAML is malformed.  The error message includes the file path
        and line number.
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    raw: dict[str, Any]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = f" (line {mark.line + 1})" if mark is not None else ""
        raise yaml.YAMLError(f"Invalid YAML in {path}{line}: {exc}") from exc

    raw = _resolve_env_vars_recursively(raw)
    return _dict_to_config(raw)


def _dict_to_config(raw: dict[str, Any]) -> Config:
    """Convert a nested dict (from YAML) into a :class:`Config` tree."""
    project_raw: dict[str, Any] = raw.get("project", {}) or {}
    llm_raw: dict[str, Any] = raw.get("llm", {}) or {}

    # --- Parse llm.fallback (list of LLMConfig) ---
    fallback_raw: list[dict[str, Any]] = llm_raw.get("fallback", []) or []
    fallback = [
        LLMConfig(
            provider=str(f.get("provider", "")),
            model=str(f.get("model", "")),
            api_key=str(f.get("api_key", "")),
            base_url=str(f.get("base_url", "")),
            json_mode=bool(f.get("json_mode", False)),
            reasoning_model=bool(f.get("reasoning_model", False)),
            timeout=float(f.get("timeout", 120.0)),
        )
        for f in fallback_raw
    ]

    # --- Parse llm.tasks (dict of LLMTaskConfig) ---
    tasks_raw: dict[str, Any] = llm_raw.get("tasks", {}) or {}
    tasks: dict[str, LLMTaskConfig] = {}
    for task_name, task_cfg_raw in tasks_raw.items():
        tc = task_cfg_raw or {}
        tasks[str(task_name)] = LLMTaskConfig(
            model=str(tc.get("model", "")),
            provider=str(tc.get("provider", "")),
            max_tokens=int(tc.get("max_tokens", 0)),
        )

    domains_raw: list[dict[str, Any]] = raw.get("domains", []) or []

    domains = []
    for d in domains_raw:
        sources_raw: list[dict[str, Any]] = d.get("sources", []) or []
        sources = []
        for s in sources_raw:
            tier = s.get("quality_tier", 1)
            tos = s.get("tos_classification")
            if not tos:
                tos = TIER_TOS_MAP.get(tier, "open")
            raw_settings = {k: v for k, v in s.items() if k not in SOURCE_CORE_KEYS}
            # Flatten YAML's nested 'settings' key into the top level
            inner = raw_settings.pop("settings", None)
            if isinstance(inner, dict):
                raw_settings.update(inner)
            sources.append(
                SourceConfig(
                    name=s.get("name", ""),
                    type=s.get("type", "api"),
                    url=s.get("url", ""),
                    quality_tier=tier,
                    tos_classification=tos,
                    fetch_depth=s.get("fetch_depth", "abstract"),
                    requires_key=s.get("requires_key", False),
                    settings=raw_settings,
                )
            )
        topics_raw: list[dict[str, Any]] = d.get("topics", []) or []
        topics = [
            TopicConfig(
                name=t.get("name", ""),
                keywords=t.get("keywords", []),
                group=t.get("group", ""),
                relevance_threshold=int(t.get("relevance_threshold", 30)),
            )
            for t in topics_raw
        ]
        # --- Parse per-domain quality_gates ---
        domain_qg_raw: dict[str, Any] = _normalize_gate_config_keys(
            d.get("quality_gates", {}) or {}
        )
        domain_quality_gates: dict[str, QualityGateConfig] = {}
        for gate_name, gc_raw in domain_qg_raw.items():
            gc = gc_raw or {}
            domain_quality_gates[str(gate_name)] = QualityGateConfig(
                name=str(gate_name),
                category=str(gc.get("category", "soft")),
                retries=int(gc.get("retries", 0)),
                retry_models=list(gc.get("retry_models", [])),
                action=str(gc.get("action", "flag")),
                threshold=gc.get("threshold", None),
                window_days=int(gc.get("window_days", 0)),
                enabled=_as_bool(gc.get("enabled", True)),
            )
        # --- Parse per-domain delivery_gates ---
        domain_dg_raw: dict[str, Any] = d.get("delivery_gates", {}) or {}
        domain_delivery_gates: dict[str, DeliveryGateConfig] = {}
        for dg_name, dc_raw in domain_dg_raw.items():
            dc = dc_raw or {}
            domain_delivery_gates[str(dg_name)] = DeliveryGateConfig(
                name=str(dg_name),
                enabled=bool(dc.get("enabled", True)),
                action_on_failure=str(dc.get("action_on_failure", "block")),
            )
        domains.append(
            DomainConfig(
                name=d.get("name", ""),
                active=bool(d.get("active", True)),
                sources=sources,
                topics=topics,
                extract_fields=d.get("extract_fields", []),
                search_mode=str(d.get("search_mode", "keyword")),
                webhook_urls=list(d.get("webhook_urls", [])),
                quality_gates=domain_quality_gates,
                delivery_gates=domain_delivery_gates,
                auto_keyword_discovery=_as_bool(
                    d.get("auto_keyword_discovery", True)
                ),
                max_auto_keywords=int(d.get("max_auto_keywords", 100)),
                auto_keyword_min_length=int(d.get("auto_keyword_min_length", 2)),
            )
        )

    # --- Parse v1.5 sections: quality_gates & delivery_gates ---
    quality_gates_raw: dict[str, Any] = _normalize_gate_config_keys(
        raw.get("quality_gates", {}) or {}
    )
    quality_gates: dict[str, QualityGateConfig] = {}
    for gate_name, gc_raw in quality_gates_raw.items():
        gc = gc_raw or {}
        quality_gates[str(gate_name)] = QualityGateConfig(
            name=str(gate_name),
            category=str(gc.get("category", "soft")),
            retries=int(gc.get("retries", 0)),
            retry_models=list(gc.get("retry_models", [])),
            action=str(gc.get("action", "flag")),
            threshold=gc.get("threshold", None),
            window_days=int(gc.get("window_days", 0)),
            enabled=_as_bool(gc.get("enabled", True)),
        )

    delivery_gates_raw: dict[str, Any] = raw.get("delivery_gates", {}) or {}
    delivery_gates: dict[str, DeliveryGateConfig] = {}
    for dg_name, dc_raw in delivery_gates_raw.items():
        dc = dc_raw or {}
        delivery_gates[str(dg_name)] = DeliveryGateConfig(
            name=str(dg_name),
            enabled=bool(dc.get("enabled", True)),
            action_on_failure=str(dc.get("action_on_failure", "block")),
        )

    # --- Parse cost_rates section ---
    cost_rates_raw: dict[str, Any] = raw.get("cost_rates", {}) or {}
    llm_rates_raw: dict[str, Any] = cost_rates_raw.get("llm", {}) or {}
    llm_rates: dict[str, LLMRateConfig] = {}
    for model_name, rate_cfg in llm_rates_raw.items():
        rc = rate_cfg or {}
        llm_rates[str(model_name)] = LLMRateConfig(
            input_per_1k=float(rc.get("input_per_1k", 0.0)),
            output_per_1k=float(rc.get("output_per_1k", 0.0)),
        )
    api_calls_raw: dict[str, Any] = cost_rates_raw.get("api_calls", {}) or {}
    api_call_rates: dict[str, ApiCallRateConfig] = {}
    for source_name, rate_cfg in api_calls_raw.items():
        rc = rate_cfg or {}
        api_call_rates[str(source_name)] = ApiCallRateConfig(
            per_call=float(rc.get("per_call", 0.0)),
        )
    storage_raw: dict[str, Any] = cost_rates_raw.get("storage", {}) or {}
    storage_rate = StorageRateConfig(
        per_item=float(storage_raw.get("per_item", 0.001)),
        per_mb=float(storage_raw.get("per_mb", 0.01)),
    )

    # --- Parse cost_alerts section ---
    cost_alerts_raw: dict[str, Any] = raw.get("cost_alerts", {}) or {}
    cost_alerts = CostAlertsConfig(
        budget_thresholds=list(cost_alerts_raw.get("budget_thresholds", [50.0, 75.0, 90.0, 100.0])),
        auto_remediation_enabled=bool(cost_alerts_raw.get("auto_remediation_enabled", False)),
        alert_webhook=str(cost_alerts_raw.get("alert_webhook", "")),
    )

    # --- Parse new v1.2 sections ---
    def _dict_or_empty(key: str) -> dict[str, Any]:
        return raw.get(key, {}) or {}

    cefr_raw = _dict_or_empty("cefr")
    email_raw = _dict_or_empty("email")
    rest_api_raw = _dict_or_empty("rest_api")
    stripe_raw = _dict_or_empty("stripe")
    vector_search_raw = _dict_or_empty("vector_search")
    cron_raw = _dict_or_empty("cron")
    multi_user_raw = _dict_or_empty("multi_user")
    tts_raw = _dict_or_empty("tts")
    output_raw = _dict_or_empty("output")

    return Config(
        project=ProjectConfig(
            name=str(project_raw.get("name", "")),
            project_name=str(project_raw.get("project_name", "")),
            created_at=str(project_raw.get("created_at", "")),
        ),
        llm=LLMConfig(
            provider=str(llm_raw.get("provider", "")),
            model=str(llm_raw.get("model", "")),
            api_key=str(llm_raw.get("api_key", "")),
            base_url=str(llm_raw.get("base_url", "")),
            json_mode=bool(llm_raw.get("json_mode", False)),
            reasoning_model=bool(llm_raw.get("reasoning_model", False)),
            timeout=float(llm_raw.get("timeout", 120.0)),
            max_tokens=int(llm_raw["max_tokens"]) if llm_raw.get("max_tokens") else None,
            fallback=fallback,
            tasks=tasks,
        ),
        domains=domains,
        cefr=CEFRConfig(
            enabled=bool(cefr_raw.get("enabled", False)),
            languages=list(cefr_raw.get("languages", ["en", "zh", "ja"])),
            model=str(cefr_raw.get("model", "")),
        ),
        email=EmailConfig(
            smtp_host=str(email_raw.get("smtp_host", "")),
            smtp_port=int(email_raw.get("smtp_port", 587)),
            smtp_user=str(email_raw.get("smtp_user", "")),
            smtp_pass=str(email_raw.get("smtp_pass", "")),
            from_addr=str(email_raw.get("from_addr", "")),
            to_addrs=list(email_raw.get("to_addrs", [])),
            enabled=bool(email_raw.get("enabled", False)),
        ),
        rest_api=RestAPIConfig(
            enabled=bool(rest_api_raw.get("enabled", True)),
            port=int(rest_api_raw.get("port", 8741)),
            host=str(rest_api_raw.get("host", "127.0.0.1")),
        ),
        stripe=StripeConfig(
            webhook_secret=str(stripe_raw.get("webhook_secret", "")),
        ),
        vector_search=VectorSearchConfig(
            enabled=bool(vector_search_raw.get("enabled", False)),
            model=str(vector_search_raw.get("model", "")),
            hybrid_weight_fts5=float(vector_search_raw.get("hybrid_weight_fts5", 0.7)),
            hybrid_weight_vector=float(vector_search_raw.get("hybrid_weight_vector", 0.3)),
        ),
        cron=CronConfig(
            auto_install=bool(cron_raw.get("auto_install", False)),
            install_path=str(cron_raw.get("install_path", "")),
        ),
        multi_user=MultiUserConfig(
            enabled=bool(multi_user_raw.get("enabled", False)),
            default_user_id=str(multi_user_raw.get("default_user_id", "default")),
        ),
        quality_gates=quality_gates,
        delivery_gates=delivery_gates,
        cost_rates=CostRatesConfig(
            llm=llm_rates,
            api_calls=api_call_rates,
            storage=storage_rate,
        ),
        cost_alerts=cost_alerts,
        tts=TTSConfig(
            # Issue #210/#218: default must match TTSConfig.engine ("local").
            # The dataclass default alone is bypassed by this YAML parser.
            engine=str(tts_raw.get("engine", "local")),
            local_voice=str(tts_raw.get("local_voice", "en-US-JennyNeural")),
        ),
        output=OutputConfig(
            pdf_timeout=float(output_raw.get("pdf_timeout", 120.0)),
            source_tier_badge=_as_bool(output_raw.get("source_tier_badge", True)),
        ),
    )


# ---------------------------------------------------------------------------
# Config path discovery
# ---------------------------------------------------------------------------


def get_config_path() -> Path | None:
    """Locate the configuration file.

    Checks (in order):
    1. ``$PWD/.autoinfo/config.yaml``
    2. ``~/.autoinfo/config.yaml``

    Returns ``None`` when neither file exists.
    """
    candidates = [
        Path.cwd() / ".autoinfo" / "config.yaml",
        Path.home() / ".autoinfo" / "config.yaml",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_config(config: Config) -> list[str]:
    """Validate *config* and return a list of error messages.

    Returns an empty list when the configuration is valid.
    """
    errors: list[str] = []

    if not config.project.name:
        errors.append("project.name is required")

    if not config.llm.provider:
        errors.append("llm.provider is required")
    if not config.llm.model:
        errors.append("llm.model is required")

    # --- Validate quality_gates (both global and per-domain) ---
    all_gate_confs: list[tuple[str, str, QualityGateConfig]] = [
        ("global", gn, gc) for gn, gc in config.quality_gates.items()
    ]
    for domain in config.domains:
        for gn, gc in domain.quality_gates.items():
            all_gate_confs.append((f"domain '{domain.name}'", gn, gc))

    for scope, gate_name, gc in all_gate_confs:
        if gc.category == "hard" and gc.action not in HARD_GATE_ACTIONS:
            errors.append(
                f"quality_gates.{gate_name} ({scope}): hard gate action must be "
                f"'block' or 'retry', got '{gc.action}'"
            )
        elif gc.category == "soft" and gc.action not in SOFT_GATE_ACTIONS:
            errors.append(
                f"quality_gates.{gate_name} ({scope}): soft gate action must be "
                f"'retry', 'flag', 'skip', or 'archive', got '{gc.action}'"
            )

    active_domains = [d for d in config.domains if d.active]
    if not active_domains:
        errors.append("at least one domain must be active")

    for domain in active_domains:
        if not domain.name:
            errors.append("active domain missing name")
        if not domain.sources:
            errors.append(
                f"active domain '{domain.name or '(unnamed)'}' "
                "must have at least one source"
            )
        if domain.search_mode not in ("keyword", "hybrid"):
            errors.append(
                f"domain '{domain.name}'.search_mode must be 'keyword' or 'hybrid', "
                f"got '{domain.search_mode}'"
            )

    return errors


def create_default_config(domain: str) -> dict[str, Any]:
    """Generate a minimal default configuration for *domain*.

    The returned dict is suitable for writing to ``.autoinfo/config.yaml``.
    Includes default quality gates (G0-G5) and delivery gates (D1-D3).
    """
    return {
        "project": {
            "name": f"autoinfo-{domain}",
            "created_at": "",
        },
        "llm": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key": "${AUTOINFO_LLM_API_KEY}",
        },
        "domains": [
            {
                "name": domain,
                "active": True,
                "sources": [],
                "topics": [],
            }
        ],
        "quality_gates": {
            "G0": {"category": "hard", "retries": 1, "action": "block"},
            "G1": {"category": "soft", "action": "flag"},
            "G1-TosCompliance": {"category": "soft", "action": "flag"},
            "G2": {"category": "soft", "action": "flag", "window_days": 30},
            "G3": {"category": "soft", "retries": 2, "action": "archive", "threshold": 30},
            "G4": {
                "category": "hard",
                "retries": 3,
                "retry_models": ["deepseek/deepseek-chat", "anthropic/claude-sonnet-4"],
                "action": "block",
            },
            "G5": {"category": "soft", "retries": 2, "action": "flag"},
        },
        "delivery_gates": {
            "D1": {"enabled": True, "action_on_failure": "block"},
            "D2": {"enabled": True, "action_on_failure": "fallback"},
            "D3": {"enabled": True, "action_on_failure": "flag"},
        },
        "cost_alerts": {
            "budget_thresholds": [50.0, 75.0, 90.0, 100.0],
            "auto_remediation_enabled": False,
            "alert_webhook": "",
        },
    }


# ---------------------------------------------------------------------------
# Configuration write-back
# ---------------------------------------------------------------------------


def config_to_dict(config: Config) -> dict[str, Any]:
    """Serialize a ``Config`` dataclass tree to a plain nested dict.

    The returned dict is suitable for writing back to a YAML file via
    ``yaml.dump``.  Domain ``search_mode`` and ``extract_fields`` are
    omitted when they carry default / empty values so that the YAML
    stays clean.
    """
    raw: dict[str, Any] = {
        "project": {
            "name": config.project.name,
            "created_at": config.project.created_at,
        },
        "llm": {
            "provider": config.llm.provider,
            "model": config.llm.model,
            "api_key": config.llm.api_key,
            "base_url": config.llm.base_url,
            "json_mode": config.llm.json_mode,
            "reasoning_model": config.llm.reasoning_model,
            "timeout": config.llm.timeout,
            "fallback": [
                {
                    "provider": f.provider,
                    "model": f.model,
                    "base_url": f.base_url,
                    "api_key": f.api_key,
                    "json_mode": f.json_mode,
                    "reasoning_model": f.reasoning_model,
                    "timeout": f.timeout,
                }
                for f in config.llm.fallback
            ],
        },
        "domains": [],
    }
    # Only include project_name when non-empty (backward compat)
    if config.project.project_name:
        raw["project"]["project_name"] = config.project.project_name
    # Only include max_tokens when set (None keeps the 2000 default)
    if config.llm.max_tokens is not None:
        raw["llm"]["max_tokens"] = config.llm.max_tokens
    # Serialize llm.tasks
    if config.llm.tasks:
        raw["llm"]["tasks"] = {}
        for task_name, tc in config.llm.tasks.items():
            raw["llm"]["tasks"][task_name] = {
                k: v for k, v in {
                    "model": tc.model,
                    "provider": tc.provider,
                    "max_tokens": tc.max_tokens,
                }.items() if v
            }

    # Serialize v1.2 config sections
    raw["cefr"] = {
        "enabled": config.cefr.enabled,
        "languages": config.cefr.languages,
        "model": config.cefr.model,
    }
    raw["email"] = {
        "smtp_host": config.email.smtp_host,
        "smtp_port": config.email.smtp_port,
        "smtp_user": config.email.smtp_user,
        "smtp_pass": config.email.smtp_pass,
        "from_addr": config.email.from_addr,
        "to_addrs": config.email.to_addrs,
        "enabled": config.email.enabled,
    }
    raw["rest_api"] = {
        "enabled": config.rest_api.enabled,
        "port": config.rest_api.port,
        "host": config.rest_api.host,
    }
    raw["stripe"] = {
        "webhook_secret": config.stripe.webhook_secret,
    }
    raw["vector_search"] = {
        "enabled": config.vector_search.enabled,
        "model": config.vector_search.model,
        "hybrid_weight_fts5": config.vector_search.hybrid_weight_fts5,
        "hybrid_weight_vector": config.vector_search.hybrid_weight_vector,
    }
    raw["cron"] = {
        "auto_install": config.cron.auto_install,
        "install_path": config.cron.install_path,
    }
    raw["multi_user"] = {
        "enabled": config.multi_user.enabled,
        "default_user_id": config.multi_user.default_user_id,
    }

    # --- Serialize cost_rates ---
    if config.cost_rates.llm or config.cost_rates.api_calls or config.cost_rates.storage:
        cost_rates_dict: dict[str, Any] = {}
        if config.cost_rates.llm:
            cost_rates_dict["llm"] = {
                model: {
                    "input_per_1k": rate.input_per_1k,
                    "output_per_1k": rate.output_per_1k,
                }
                for model, rate in config.cost_rates.llm.items()
            }
        if config.cost_rates.api_calls:
            cost_rates_dict["api_calls"] = {
                source: {"per_call": rate.per_call}
                for source, rate in config.cost_rates.api_calls.items()
            }
        cost_rates_dict["storage"] = {
            "per_item": config.cost_rates.storage.per_item,
            "per_mb": config.cost_rates.storage.per_mb,
        }
        raw["cost_rates"] = cost_rates_dict

    # --- Serialize cost_alerts ---
    ca = config.cost_alerts
    raw["cost_alerts"] = {
        "budget_thresholds": ca.budget_thresholds,
        "auto_remediation_enabled": ca.auto_remediation_enabled,
        "alert_webhook": ca.alert_webhook,
    }

    # --- Serialize v1.5 quality_gates & delivery_gates ---
    if config.quality_gates:
        raw["quality_gates"] = {}
        for gate_name, gc in config.quality_gates.items():
            entry: dict[str, Any] = {
                "category": gc.category,
                "retries": gc.retries,
                "action": gc.action,
            }
            if gc.retry_models:
                entry["retry_models"] = gc.retry_models
            if gc.threshold is not None:
                entry["threshold"] = gc.threshold
            if gc.window_days:
                entry["window_days"] = gc.window_days
            if not gc.enabled:
                entry["enabled"] = gc.enabled
            raw["quality_gates"][gate_name] = entry
    if config.delivery_gates:
        raw["delivery_gates"] = {}
        for dg_name, dc in config.delivery_gates.items():
            raw["delivery_gates"][dg_name] = {
                "enabled": dc.enabled,
                "action_on_failure": dc.action_on_failure,
            }

    for domain in config.domains:
        domain_dict: dict[str, Any] = {
            "name": domain.name,
            "active": domain.active,
            "sources": [
                {
                    "name": s.name,
                    "type": s.type,
                    "url": s.url,
                    "quality_tier": s.quality_tier,
                    "tos_classification": s.tos_classification,
                    **({"fetch_depth": s.fetch_depth} if s.fetch_depth != "abstract" else {}),
                    **({"requires_key": s.requires_key} if s.requires_key else {}),
                    **s.settings,
                }
                for s in domain.sources
            ],
            "topics": [
                {
                    "name": t.name,
                    "keywords": t.keywords,
                    **({"group": t.group} if t.group else {}),
                    **(
                        {"relevance_threshold": t.relevance_threshold}
                        if t.relevance_threshold != 30
                        else {}
                    ),
                }
                for t in domain.topics
            ],
        }
        if domain.extract_fields:
            domain_dict["extract_fields"] = domain.extract_fields
        if domain.search_mode != "keyword":
            domain_dict["search_mode"] = domain.search_mode
        if not domain.auto_keyword_discovery:
            domain_dict["auto_keyword_discovery"] = False
        if domain.max_auto_keywords != 100:
            domain_dict["max_auto_keywords"] = domain.max_auto_keywords
        if domain.auto_keyword_min_length != 2:
            domain_dict["auto_keyword_min_length"] = domain.auto_keyword_min_length
        if domain.webhook_urls:
            domain_dict["webhook_urls"] = domain.webhook_urls
        if domain.quality_gates:
            domain_qg_dict: dict[str, Any] = {}
            for gate_name, gc in domain.quality_gates.items():
                domain_qg_entry: dict[str, Any] = {
                    "category": gc.category,
                    "retries": gc.retries,
                    "action": gc.action,
                }
                if gc.retry_models:
                    domain_qg_entry["retry_models"] = gc.retry_models
                if gc.threshold is not None:
                    domain_qg_entry["threshold"] = gc.threshold
                if gc.window_days:
                    domain_qg_entry["window_days"] = gc.window_days
                if not gc.enabled:
                    domain_qg_entry["enabled"] = gc.enabled
                domain_qg_dict[gate_name] = domain_qg_entry
            domain_dict["quality_gates"] = domain_qg_dict
        if domain.delivery_gates:
            domain_dg_dict: dict[str, Any] = {}
            for dg_name, dc in domain.delivery_gates.items():
                domain_dg_dict[dg_name] = {
                    "enabled": dc.enabled,
                    "action_on_failure": dc.action_on_failure,
                }
            domain_dict["delivery_gates"] = domain_dg_dict
        raw["domains"].append(domain_dict)
    return raw


def save_config(config: Config, path: Path | str) -> None:
    """Write *config* to a YAML file at *path*.

    The parent directory is created if it does not exist.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = config_to_dict(config)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(raw, fh, default_flow_style=False, sort_keys=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Effective LLM config resolution
# ---------------------------------------------------------------------------


def _resolve_task_llm_config(config: Config, task_name: str = "") -> LLMConfig:
    """Resolve effective :class:`LLMConfig` for *task_name* from an in-memory config.

    Priority (highest to lowest):
    1. Task-specific overrides from ``llm.tasks[task_name]``
    2. Base ``llm`` configuration

    Judgment task names (see :data:`JUDGMENT_TASKS`) are exempt from task
    overrides: their model ALWAYS resolves to the release-pinned
    :data:`JUDGMENT_MODEL`, so a drifted ``llm.tasks`` entry can never
    change what model judges content.

    Returns a new ``LLMConfig`` with task-level fields merged on top of
    the base config.  Falls back to the base ``LLMConfig`` when
    *task_name* is empty or unknown.
    """
    base = config.llm
    if task_name in JUDGMENT_TASKS:
        return LLMConfig(
            provider=base.provider,
            model=JUDGMENT_MODEL,
            api_key=base.api_key,
            base_url=base.base_url,
            json_mode=base.json_mode,
            reasoning_model=base.reasoning_model,
            timeout=base.timeout,
            max_tokens=base.max_tokens,
            fallback=base.fallback,
            tasks=base.tasks,
        )
    if not task_name or task_name not in base.tasks:
        return base

    task_cfg = base.tasks[task_name]
    return LLMConfig(
        provider=task_cfg.provider if task_cfg.provider else base.provider,
        model=task_cfg.model if task_cfg.model else base.model,
        api_key=base.api_key,
        base_url=base.base_url,
        json_mode=base.json_mode,
        reasoning_model=base.reasoning_model,
        timeout=base.timeout,
        max_tokens=task_cfg.max_tokens or base.max_tokens,
        fallback=base.fallback,
        tasks=base.tasks,
    )


def get_effective_llm_config(task: str | None = None) -> dict[str, Any]:
    """Resolve the effective LLM configuration for a given *task*.

    When *task* is provided and matches a key in ``llm.tasks``, task-level
    fields (model, provider, max_tokens) override the base LLM config.
    Falls back to the base config otherwise.

    Parameters
    ----------
    task:
        Optional task name (e.g. ``"extraction"``, ``"summarization"``).

    Returns
    -------
    dict
        Keys: ``task``, ``provider``, ``model``, ``max_tokens``,
        ``api_key_configured``, ``fallback_chain``.

    Raises
    ------
    RuntimeError
        When no config file is found.
    """
    config_path = get_config_path()
    if config_path is None:
        raise RuntimeError("No configuration file found. Run 'autoinfo init' first.")

    config = load_config(config_path)
    base = config.llm

    if task and task in base.tasks:
        tc = base.tasks[task]
        provider = tc.provider if tc.provider else base.provider
        model = tc.model if tc.model else base.model
        max_tokens = tc.max_tokens
    else:
        provider = base.provider
        model = base.model
        max_tokens = 0

    fallback_chain = [
        {"provider": fb.provider, "model": fb.model}
        for fb in base.fallback
    ]

    return {
        "task": task or "default",
        "provider": provider,
        "model": model,
        "max_tokens": max_tokens,
        "api_key_configured": str(bool(base.api_key or os.environ.get("AUTOINFO_LLM_API_KEY"))),
        "fallback_chain": fallback_chain,
    }


def llm_fallback_health(config: Config) -> dict[str, Any]:
    """Derive the LLM fallback-chain health state from *config*.

    Returns
    -------
    dict
        Keys: ``configured`` (bool — a non-empty ``llm.fallback`` list),
        ``count`` (int), ``entries`` (list of per-fallback-entry dicts with
        ``model``/``provider``/``inherits_provider``/``inherits_key``), and
        ``primary`` (dict with ``model``/``provider``/``reasoning_model``/
        ``json_mode``).

        ``inherits_provider`` is True when the entry's ``provider`` is empty
        (``call_with_fallback`` resolves it to the primary provider);
        ``inherits_key`` is True when the entry's ``api_key`` is empty (the
        primary key — or its ``${ENV}`` reference — applies).  An explicit
        ``${ENV}`` reference on the entry is NOT inheritance.
    """
    llm = config.llm
    primary = {
        "model": llm.model,
        "provider": llm.provider,
        "reasoning_model": llm.reasoning_model,
        "json_mode": llm.json_mode,
    }
    entries = [
        {
            "model": fb.model,
            "provider": fb.provider,
            "inherits_provider": not bool(fb.provider),
            "inherits_key": not bool(fb.api_key),
        }
        for fb in llm.fallback
    ]
    return {
        "configured": bool(llm.fallback),
        "count": len(llm.fallback),
        "entries": entries,
        "primary": primary,
    }


def ensure_config_exists() -> None:
    """Exit with an error message when no configuration file is found."""
    if get_config_path() is None:
        print("Run 'autoinfo init' first", file=sys.stderr)
        sys.exit(1)
