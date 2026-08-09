"""Data models for AutoInfo.

Pure dataclasses with serialization methods — no business logic, no persistence.
"""

from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, field
from enum import Enum
from typing import Any, Literal


@dataclass
class Item:
    """A single collected item from any source."""

    id: str
    source_name: str
    source_type: str
    source_url: str
    title: str
    content: str
    content_type: str = "text"
    source_platform: str = ""
    collected_at: str = ""
    language: str = ""
    domain: str = ""
    topic_tags: list[str] = field(default_factory=list)
    quality_tier: int = 1
    raw_data: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    previous_version: int = 0
    supersedes: str = ""
    trace_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Item:
        """Create Item from dict with resilience to missing/extra keys.

        Only accepts known fields from ``Item.__dataclass_fields__``;
        unknown keys are silently ignored.  Missing fields are filled
        with their declared default, default_factory, or an empty string.
        """
        valid_fields = cls.__dataclass_fields__

        # Accept only keys that match Item's dataclass fields
        filtered = {k: v for k, v in data.items() if k in valid_fields}

        # Fill missing fields with defaults
        for field_name, field_def in valid_fields.items():
            if field_name in filtered:
                continue
            if field_def.default is not MISSING:
                filtered[field_name] = field_def.default
            elif field_def.default_factory is not MISSING:
                filtered[field_name] = field_def.default_factory()
            else:
                # Required field without a default — use empty string
                filtered[field_name] = ""

        try:
            return cls(**filtered)
        except Exception as exc:
            raise TypeError(
                f"Cannot create Item from data: {exc}"
            ) from exc


@dataclass
class CollectionResult:
    """Result of a collection run against one or more sources."""

    collection_id: str
    domain: str
    source: str = ""
    status: str = ""
    items_found: int = 0
    items_new: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    source_failed: bool = False
    duration_s: float = 0.0
    estimated_duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CollectionStats:
        return cls(**data)


class ProductType(Enum):
    """Type of deliverable product."""

    RAW = "raw"
    PROCESSED = "processed"


@dataclass
class Product:
    """A deliverable product configured for a domain."""

    id: str
    domain: str
    type: ProductType
    name: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    templates: list[str] = field(default_factory=list)
    delivery_channels: list[str] = field(default_factory=list)
    quality_gates: dict[str, Any] = field(default_factory=dict)
    variants: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value  # serialize enum to its string value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Product:
        data = dict(data)
        if "type" in data and isinstance(data["type"], str):
            data["type"] = ProductType(data["type"])
        return cls(**data)


@dataclass
class DeliveryResult:
    """Result of delivering a product through a specific channel."""

    product_id: str
    channel: str
    status: Literal["success", "failed", "partial"]
    timestamp: str = ""
    recipient_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeliveryResult:
        return cls(**data)


@dataclass
class AlertRule:
    """Threshold-based alert rule for triggering notifications.

    ``kind`` discriminates the rule's trigger surface:

    * ``"content"`` (default) — the legacy behavior: match collected items
      by keyword + relevance threshold via :func:`alerts.check_alerts`.
    * ``"source_credential_missing"`` — fires when a configured source
      requires an API key/credential that is absent from the operator
      environment (B3 escalation: only the B3 human can supply the key).
      Evaluated by :func:`alerts.check_source_alerts`.
    """

    id: str
    domain: str
    topic_keywords: list[str] = field(default_factory=list)
    relevance_threshold: float = 0.0
    channel: Literal["email", "webhook"] = "email"
    enabled: bool = True
    kind: str = "content"  # "content" | "source_credential_missing"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AlertRule:
        return cls(**data)


@dataclass
class KBEntry:
    """An entry in the knowledge base pipeline (01-Raw / 02-Draft / 03-Wiki)."""

    entry_id: str
    title: str
    domain: str
    tier: str = "01-Raw"
    source_url: str = ""
    source_type: str = ""
    source_platform: str = ""
    collected_at: str = ""
    summary: str = ""
    extracted_fields: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    priority: int = 3
    language: str = ""
    quality_tier: int = 1
    relevance_score: float = 0.0
    dedup_status: str = "unique"
    source_score: float = 0.0
    file_path: str = ""
    custom_fields: dict[str, Any] = field(default_factory=dict)
    # --- KB frontmatter fields expanded in v1.1 ---
    author: str = ""
    source_ids: list[str] = field(default_factory=list)
    status: str = "active"  # "active", "deprecated", "archived"
    related_concepts: list[str] = field(default_factory=list)
    linked_entries: list[str] = field(default_factory=list)
    quality_flags: dict[str, bool] = field(default_factory=dict)
    user_id: str = ""  # Multi-user support — empty string means "all users"
    version: int = 1
    previous_version: int = 0
    supersedes: str = ""
    trace_id: str = ""  # Per-item pipeline traceability — UUID from collection, resolvable via trace_item  # noqa: E501
    # ToS compliance metadata from G1-TosCompliance gate (written to frontmatter
    # by _entry_to_frontmatter; kept as a field so from_dict parses cleanly).
    tos_compliant: bool | None = None
    tos_classification: str | None = None
    # KB promotion provenance — frontmatter-only (no DB column); how a Draft
    # reached 03-Wiki ("agent" | "director") and which actor promoted it.
    promotion_source: str | None = None
    promoted_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KBEntry:
        return cls(**data)


@dataclass
class ExtractionResult:
    """Structured extraction output from LLM processing."""

    item_id: str
    title: str = ""
    tl_dr: str = ""
    key_points: list[str] = field(default_factory=list)
    entities: list[dict[str, Any]] = field(default_factory=list)
    relevance_score: float = 0.0
    custom_fields: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExtractionResult:
        return cls(**data)


@dataclass
class SourceHealth:
    """Health status for a single source."""

    source_id: str
    status: str = "unknown"
    last_success: str = ""
    error_count: int = 0
    avg_response_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceHealth:
        return cls(**data)


@dataclass
class ItemRelation:
    """A link between two KB entries."""

    relation_id: str
    item_a_id: str
    item_b_id: str
    relation_type: str = "related"
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ItemRelation:
        return cls(**data)


@dataclass
class CollectionStats:
    """Aggregated collection statistics across a period."""

    period: str = "daily"
    date_from: str = ""
    date_to: str = ""
    total_items: int = 0
    new_items: int = 0
    duplicate_items: int = 0
    domains: dict[str, int] = field(default_factory=dict)
    sources: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CollectionStats:
        return cls(**data)


@dataclass
class DeliveryLog:
    """A single delivery attempt record (append-only log)."""

    log_id: str
    subscription_id: str
    channel: str
    message_type: str
    status: str
    attempt_count: int = 0
    last_attempt: str = ""
    error_message: str = ""
    sla_tier: str = "standard"


@dataclass
class AuditLog:
    """Immutable audit log entry."""

    log_id: str
    timestamp: str
    actor: str
    action: str
    resource_type: str
    resource_id: str
    details: dict[str, Any] = field(default_factory=dict)
    ip_address: str = ""


@dataclass
class UserProfile:
    """End-user profile with lifecycle status (trial→active→suspended→cancelled)."""

    user_id: str
    name: str
    email: str = ""
    status: str = "trial"
    tier: str = "free"
    delivery_preferences: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    trial_ends_at: str = ""
    trial_started_at: str = ""
    trial_days: int = 14
    grace_period_days: int = 7
    last_login_at: str = ""
    preferences: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Stripe billing fields
    stripe_customer_id: str = ""
    stripe_subscription_id: str = ""


@dataclass
class Subscription:
    """Subscription tied to a user profile with plan, status, and billing info.

    CD-024 fields: tier, channels, domains, products, platform_limit,
    domain_limit, raw_access, processed_access.
    """

    subscription_id: str
    user_id: str
    plan: str = "free"
    status: str = "active"
    start_date: str = ""
    end_date: str = ""
    auto_renew: bool = True
    price_monthly: float = 0.0
    currency: str = "USD"
    features: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    tier: str = "free"
    channels: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    products: list[str] = field(default_factory=list)
    platform_limit: int = 1
    domain_limit: int = 1
    raw_access: bool = False
    processed_access: bool = True
