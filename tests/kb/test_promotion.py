"""Tests for the KB promotion admission module (T3 — autoinfo/promotion.py)
and the promote admission-gate wiring (T2 — KBStore.promote_kb_draft).

T3 groups (pure gate unit tests):
  1. Provenance — missing/unresolvable/incomplete source provenance rejects
     with enumerated, typed rejection reasons.
  2. Thresholds — G1 source_score / G3 relevance_score below the threshold
     reject; configurable thresholds (per-domain quality_gates) are honored.
  3. G4 curation gate — enabled by default: a factually-inconsistent draft
     body hard-rejects; disabled via config: G4 is not run.
Plus a happy path: a fully-complete entry passes admission with reason "ok".

T2 groups (KBStore integration — the gate wired into promote_kb_draft):
  4. Rejection — a draft failing admission raises ``PromotionRejected``,
     writes a ``_failed/<domain>/<entry_id>.md`` marker, and stays in
     02-Draft (not promoted, not deleted).
  5. Acceptance — a fully-eligible draft promotes to 03-Wiki with
     ``promotion_source: agent`` in frontmatter and no ``human_promoted``.

G4 is an LLM call; tests monkeypatch ``autoinfo.promotion.G4FactualConsistency``
with a fake checker (no real LLM is ever invoked).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from autoinfo.config import Config, DomainConfig, QualityGateConfig
from autoinfo.kb import KBStore, PromotionRejected
from autoinfo.models import Item, KBEntry
from autoinfo.promotion import AdmissionResult, RejectionReason, check_promotion_admission
from autoinfo.quality import QualityResult

# ===================================================================
# Fixtures / builders
# ===================================================================


def make_entry(**overrides: object) -> KBEntry:
    """Build a complete, admission-ready 02-Draft entry."""
    entry = KBEntry(
        entry_id="medical-research-draft-time-lapse",
        title="Time-lapse imaging in IVF",
        domain="medical-research",
        tier="02-Draft",
        source_url="https://example.com/paper1",
        source_type="api",
        source_platform="pubmed",
        summary="Time-lapse embryo imaging improves IVF selection.",
        source_score=72.0,
        relevance_score=85.0,
        quality_tier=1,
        source_ids=["raw-001"],
    )
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


def make_raw(**overrides: object) -> KBEntry:
    """Build a complete 01-Raw source entry with mandatory provenance."""
    entry = KBEntry(
        entry_id="raw-001",
        title="Raw source paper",
        domain="medical-research",
        tier="01-Raw",
        source_url="https://example.com/paper1",
        source_type="api",
        source_platform="pubmed",
        quality_tier=1,
        source_score=72.0,
        relevance_score=85.0,
    )
    for key, value in overrides.items():
        setattr(entry, key, value)
    return entry


def resolver(raws: list[KBEntry]) -> Callable[[str], KBEntry | None]:
    """Build a ``resolve_raw`` callable from a list of Raw entries."""
    by_id: dict[str, KBEntry] = {r.entry_id: r for r in raws}
    return lambda rid: by_id.get(rid)


def build_config(
    *domains: DomainConfig,
    global_gates: dict[str, QualityGateConfig] | None = None,
) -> Config:
    """Build a minimal :class:`Config` with optional gate overrides."""
    return Config(quality_gates=global_gates or {}, domains=list(domains))


def domain_cfg(
    domain: str = "medical-research",
    gates: dict[str, QualityGateConfig] | None = None,
) -> DomainConfig:
    return DomainConfig(name=domain, quality_gates=gates or {})


def patch_g4(
    monkeypatch: pytest.MonkeyPatch,
    passed: bool,
) -> list[tuple[object, object]]:
    """Monkeypatch the module-level G4 class; returns the recorded (item, extraction) calls.

    The fake accepts any constructor kwargs (model/json_mode/timeout) and
    returns a canned :class:`QualityResult` from every ``check`` call.
    """
    result = g4_result(passed)
    calls: list[tuple[object, object]] = []

    class _FakeG4:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def check(
            self,
            item: object,
            extraction: object,
            gate_config: QualityGateConfig | None = None,  # noqa: ARG002
        ) -> QualityResult:
            calls.append((item, extraction))
            return result

    monkeypatch.setattr(
        "autoinfo.promotion.G4FactualConsistency",
        _FakeG4,
    )
    return calls


def g4_result(passed: bool) -> QualityResult:
    if passed:
        return QualityResult(
            gate_name="G4-SummaryFactual",
            passed=True,
            score=1.0,
            details={"contradiction": False},
        )
    return QualityResult(
        gate_name="G4-SummaryFactual",
        passed=False,
        flagged=True,
        score=0.0,
        details={"contradiction": True, "action": "block"},
    )


# ===================================================================
# Group 1 — provenance completeness
# ===================================================================


class TestProvenance:
    def test_missing_source_ids_rejected(self) -> None:
        entry = make_entry(source_ids=[])
        result = check_promotion_admission(
            entry,
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw()]),
        )
        assert not result.allowed
        assert RejectionReason.PROVENANCE_MISSING in result.reasons

    def test_unresolvable_source_rejected(self) -> None:
        entry = make_entry(source_ids=["raw-001", "raw-ghost"])
        result = check_promotion_admission(
            entry,
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw()]),
        )
        assert not result.allowed
        assert RejectionReason.PROVENANCE_UNRESOLVABLE in result.reasons

    def test_unresolvable_source_without_resolver_rejected(self) -> None:
        """No resolver supplied — provenance cannot be verified, fail closed."""
        result = check_promotion_admission(
            make_entry(),
            "medical-research",
            build_config(),
        )
        assert not result.allowed
        assert RejectionReason.PROVENANCE_UNRESOLVABLE in result.reasons

    def test_raw_missing_source_url_rejected(self) -> None:
        entry = make_entry()
        result = check_promotion_admission(
            entry,
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw(source_url="")]),
        )
        assert not result.allowed
        assert RejectionReason.PROVENANCE_INCOMPLETE in result.reasons

    def test_raw_missing_source_type_rejected(self) -> None:
        result = check_promotion_admission(
            make_entry(),
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw(source_type="")]),
        )
        assert not result.allowed
        assert RejectionReason.PROVENANCE_INCOMPLETE in result.reasons

    def test_raw_missing_source_platform_rejected(self) -> None:
        result = check_promotion_admission(
            make_entry(),
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw(source_platform="")]),
        )
        assert not result.allowed
        assert RejectionReason.PROVENANCE_INCOMPLETE in result.reasons

    def test_complete_provenance_allows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        patch_g4(monkeypatch, passed=True)
        result = check_promotion_admission(
            make_entry(),
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw()]),
        )
        assert result.allowed
        assert result.reasons == [RejectionReason.OK]


# ===================================================================
# Group 2 — G1 / G3 thresholds
# ===================================================================


class TestThresholds:
    def test_source_score_below_default_rejected(self) -> None:
        result = check_promotion_admission(
            make_entry(source_score=29.9),
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw()]),
        )
        assert not result.allowed
        assert RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD in result.reasons

    def test_source_score_at_threshold_allowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patch_g4(monkeypatch, passed=True)
        result = check_promotion_admission(
            make_entry(source_score=30.0),
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw()]),
        )
        assert result.allowed
        assert result.reasons == [RejectionReason.OK]

    def test_relevance_below_default_rejected(self) -> None:
        result = check_promotion_admission(
            make_entry(relevance_score=29.9),
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw()]),
        )
        assert not result.allowed
        assert RejectionReason.RELEVANCE_BELOW_THRESHOLD in result.reasons

    def test_both_above_default_allowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patch_g4(monkeypatch, passed=True)
        result = check_promotion_admission(
            make_entry(source_score=72.0, relevance_score=85.0),
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw()]),
        )
        assert result.allowed
        assert result.reasons == [RejectionReason.OK]

    def test_configurable_g1_threshold_honored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patch_g4(monkeypatch, passed=True)
        gates = {
            "G1-SourceAuthority": QualityGateConfig(
                name="G1-SourceAuthority", threshold=50.0
            )
        }
        cfg = build_config(domain_cfg(gates=gates))
        low = check_promotion_admission(
            make_entry(source_score=40.0),
            "medical-research",
            cfg,
            resolve_raw=resolver([make_raw()]),
        )
        assert not low.allowed
        assert RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD in low.reasons
        # Same entry, but below the *default* threshold — must pass with 50.0 config
        high = check_promotion_admission(
            make_entry(source_score=60.0),
            "medical-research",
            cfg,
            resolve_raw=resolver([make_raw()]),
        )
        assert RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD not in high.reasons

    def test_configurable_g3_threshold_honored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patch_g4(monkeypatch, passed=True)
        gates = {
            "G3-RelevanceScoring": QualityGateConfig(
                name="G3-RelevanceScoring", threshold=50.0
            )
        }
        cfg = build_config(domain_cfg(gates=gates))
        low = check_promotion_admission(
            make_entry(relevance_score=40.0),
            "medical-research",
            cfg,
            resolve_raw=resolver([make_raw()]),
        )
        assert not low.allowed
        assert RejectionReason.RELEVANCE_BELOW_THRESHOLD in low.reasons
        high = check_promotion_admission(
            make_entry(relevance_score=60.0),
            "medical-research",
            cfg,
            resolve_raw=resolver([make_raw()]),
        )
        assert high.allowed

    def test_curation_gate_threshold_shared_default(self) -> None:
        """CurationGate.threshold (T4 shape) acts as shared default for G1/G3."""
        cfg = build_config(
            domain_cfg(gates={"CurationGate": QualityGateConfig(threshold=50.0)})
        )
        result = check_promotion_admission(
            make_entry(source_score=40.0, relevance_score=60.0),
            "medical-research",
            cfg,
            resolve_raw=resolver([make_raw()]),
        )
        assert not result.allowed
        assert RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD in result.reasons

    def test_global_gate_config_applies_when_domain_has_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patch_g4(monkeypatch, passed=True)
        global_gates = {
            "G1-SourceAuthority": QualityGateConfig(
                name="G1-SourceAuthority", threshold=90.0
            )
        }
        cfg = build_config(
            domain_cfg(gates={}), global_gates=global_gates
        )
        result = check_promotion_admission(
            make_entry(source_score=85.0),
            "medical-research",
            cfg,
            resolve_raw=resolver([make_raw()]),
        )
        assert not result.allowed
        assert RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD in result.reasons

    def test_domain_gate_config_overrides_global(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patch_g4(monkeypatch, passed=True)
        global_gates = {
            "G1-SourceAuthority": QualityGateConfig(
                name="G1-SourceAuthority", threshold=90.0
            )
        }
        domain_gates = {
            "G1-SourceAuthority": QualityGateConfig(
                name="G1-SourceAuthority", threshold=40.0
            )
        }
        cfg = build_config(
            domain_cfg(gates=domain_gates), global_gates=global_gates
        )
        result = check_promotion_admission(
            make_entry(source_score=50.0),
            "medical-research",
            cfg,
            resolve_raw=resolver([make_raw()]),
        )
        assert RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD not in result.reasons

    def test_g4_not_run_when_deterministic_checks_fail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail-fast: no LLM spend when provenance/threshold checks already fail."""
        calls = patch_g4(monkeypatch, passed=False)
        result = check_promotion_admission(
            make_entry(source_score=5.0),
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw()]),
        )
        assert not result.allowed
        assert calls == []


# ===================================================================
# Group 3 — CurationGate G4 factual consistency
# ===================================================================


class TestCurationG4:
    def test_g4_enabled_by_default_hard_rejects_inconsistency(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No CurationGate key in config — G4 still runs and hard-rejects."""
        calls = patch_g4(monkeypatch, passed=False)
        result = check_promotion_admission(
            make_entry(),
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw()]),
        )
        assert not result.allowed
        assert RejectionReason.G4_FACTUAL_FAILED in result.reasons
        assert len(calls) == 1

    def test_g4_enabled_via_curation_gate_config_rejects(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = patch_g4(monkeypatch, passed=False)
        cfg = build_config(
            # ``enabled`` lands on QualityGateConfig in T4 — stand in via attributes.
            domain_cfg(gates={"CurationGate": SimpleNamespace(enabled=True)})  # type: ignore[dict-item]
        )
        result = check_promotion_admission(
            make_entry(),
            "medical-research",
            cfg,
            resolve_raw=resolver([make_raw()]),
        )
        assert not result.allowed
        assert RejectionReason.G4_FACTUAL_FAILED in result.reasons
        assert len(calls) == 1

    def test_g4_pass_allows_admission(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = patch_g4(monkeypatch, passed=True)
        result = check_promotion_admission(
            make_entry(),
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw()]),
        )
        assert result.allowed
        assert result.reasons == [RejectionReason.OK]
        assert len(calls) == 1

    def test_g4_disabled_in_config_not_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CurationGate.enabled=False — G4 is skipped even for an inconsistent draft."""
        calls = patch_g4(monkeypatch, passed=False)
        cfg = build_config(
            domain_cfg(gates={"CurationGate": SimpleNamespace(enabled=False)})  # type: ignore[dict-item]
        )
        result = check_promotion_admission(
            make_entry(),
            "medical-research",
            cfg,
            resolve_raw=resolver([make_raw()]),
        )
        assert result.allowed
        assert calls == []

    def test_g4_disabled_via_dict_shaped_curation_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T4 may persist CurationGate as a raw dict — tolerate that shape too."""
        calls = patch_g4(monkeypatch, passed=False)
        cfg = build_config(
            domain_cfg(gates={"CurationGate": {"enabled": False}})  # type: ignore[dict-item]
        )
        result = check_promotion_admission(
            make_entry(),
            "medical-research",
            cfg,
            resolve_raw=resolver([make_raw()]),
        )
        assert result.allowed
        assert calls == []

    def test_g4_config_none_loads_disk_config_model(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """config=None resolves the G4 model from disk config (PR #284 guard).

        ``_run_g4_check`` must load ``.autoinfo/config.yaml`` when no Config
        object is passed, instead of hardcoding openrouter/deepseek-chat.
        """
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "llm:\n  provider: openai\n  model: regression-test-model\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("autoinfo.config.get_config_path", lambda: config_path)

        records: list[str] = []
        result = g4_result(True)

        class _RecorderG4:
            def __init__(self, model: str = "", **_: object) -> None:
                records.append(model)

            def check(self, *_: object, **__: object) -> QualityResult:
                return result

        monkeypatch.setattr("autoinfo.promotion.G4FactualConsistency", _RecorderG4)

        admission = check_promotion_admission(
            make_entry(),
            "medical-research",
            None,
            resolve_raw=resolver([make_raw()]),
        )
        assert admission.allowed is True
        assert records == ["openai/regression-test-model"]

    def test_g4_config_none_without_disk_config_falls_back_to_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No Config and no disk config — issue #195: promotion raises loudly
        (a G4 gate cannot judge without a configured model; it never silently
        calls a hardcoded vendor default)."""
        from autoinfo.config import JudgmentModelNotConfiguredError

        monkeypatch.setattr("autoinfo.config.get_config_path", lambda: None)
        with pytest.raises(JudgmentModelNotConfiguredError):
            check_promotion_admission(
                make_entry(),
                "medical-research",
                None,
                resolve_raw=resolver([make_raw()]),
            )


# ===================================================================
# Happy path — full admission pass
# ===================================================================


class TestHappyPath:
    def test_complete_entry_passes_with_ok_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        patch_g4(monkeypatch, passed=True)
        result: AdmissionResult = check_promotion_admission(
            make_entry(),
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw()]),
        )
        assert result.allowed is True
        assert result.reasons == [RejectionReason.OK]

    def test_result_is_frozen_dataclass(self) -> None:
        result = check_promotion_admission(
            make_entry(source_ids=[]),
            "medical-research",
            build_config(),
            resolve_raw=resolver([make_raw()]),
        )
        with pytest.raises(Exception):
            result.allowed = True  # type: ignore[misc]


# ===================================================================
# T2 — promote_kb_draft admission-gate wiring (KBStore integration)
# ===================================================================


@pytest.fixture
def store(tmp_path: Path) -> KBStore:
    """A KBStore rooted in a fresh temp directory."""
    return KBStore(base_path=tmp_path / "knowledge")


def make_scored_raw(
    store: KBStore,
    *,
    source_url: str = "https://example.com/paper1",
    source_platform: str = "pubmed",
    g1_score: float = 72.0,
    g3_score: float = 85.0,
    with_quality_results: bool = True,
) -> KBEntry:
    """Store a 01-Raw entry with full provenance and (optionally) real
    G1/G3 gate scores, mirroring ``test_draft_carries_forward_raw_scores``."""
    item = Item(
        id="raw-001",
        source_name="pubmed",
        source_type="api",
        source_url=source_url,
        source_platform=source_platform,
        title="Raw source paper",
        content=(
            "Time-lapse embryo imaging has been proposed as a non-invasive "
            "method to improve embryo selection in IVF cycles."
        ),
        content_type="text",
        collected_at="2026-07-15T10:30:00Z",
        language="en",
        domain="medical-research",
        topic_tags=["IVF"],
        quality_tier=2,
    )
    if not with_quality_results:
        entry = store.store_entry(item)
        assert entry is not None
        return entry
    g3 = QualityResult(
        gate_name="G3-RelevanceScoring", passed=True, score=g3_score
    )
    g1 = QualityResult(
        gate_name="G1-SourceAuthority",
        passed=True,
        score=0.0,
        details={"source_score": g1_score},
    )
    entry = store.store_entry(
        item,
        quality_results={
            "G3-RelevanceScoring": g3,
            "G1-SourceAuthority": g1,
        },
    )
    assert entry is not None
    return entry


def _marker_path(store: KBStore, entry_id: str) -> Path:
    """The ``_failed/<domain>/<entry_id>.md`` marker path for a draft."""
    return store.base_path / "_failed" / "medical-research" / f"{entry_id}.md"


class TestPromoteAdmissionGate:
    """T2 rejection path: gate blocks the move, writes a ``_failed/``
    marker, and leaves the Draft in 02-Draft."""

    def test_promote_admission_rejects_incomplete_provenance(
        self, store: KBStore
    ) -> None:
        """A draft referencing a Raw with a missing source_url is rejected."""
        raw = make_scored_raw(store, source_url="")
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="Admission reject draft",
            summary="Draft with incomplete provenance",
        )

        with pytest.raises(PromotionRejected) as exc_info:
            store.promote_kb_draft(draft_id=draft.entry_id)

        assert RejectionReason.PROVENANCE_INCOMPLETE in exc_info.value.reasons
        # _failed/<domain>/<entry_id>.md marker appears
        marker = _marker_path(store, draft.entry_id)
        assert marker.is_file()
        # Draft STILL in 02-Draft — not promoted, not deleted
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None
        assert meta["tier"] == "02-Draft"
        assert Path(draft.file_path).is_file()

    def test_promote_admission_rejects_low_scores_with_reasons(
        self, store: KBStore
    ) -> None:
        """Full provenance but zero G1/G3 scores → both reasons enumerated."""
        raw = make_scored_raw(store, with_quality_results=False)
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="Low-score reject draft",
        )

        with pytest.raises(PromotionRejected) as exc_info:
            store.promote_kb_draft(draft_id=draft.entry_id)

        reasons = exc_info.value.reasons
        assert RejectionReason.SOURCE_SCORE_BELOW_THRESHOLD in reasons
        assert RejectionReason.RELEVANCE_BELOW_THRESHOLD in reasons

        marker = _marker_path(store, draft.entry_id)
        assert marker.is_file()
        raw_text = marker.read_text(encoding="utf-8")
        end = raw_text.find("---", 3)
        fm = yaml.safe_load(raw_text[3:end])
        assert fm["gate"] == "PromotionAdmission"
        assert fm["reasons"] == [str(r) for r in reasons]
        assert fm["entry_id"] == draft.entry_id
        assert fm["tier"] == "02-Draft"
        # Draft untouched
        still_draft = store.index.get_entry(draft.entry_id)
        assert still_draft is not None and still_draft["tier"] == "02-Draft"
        assert Path(draft.file_path).is_file()

    def test_promote_admission_rejects_on_g4_failure(
        self, store: KBStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fully-eligible draft whose body fails the G4 re-check hard-rejects."""
        patch_g4(monkeypatch, passed=False)
        raw = make_scored_raw(store)
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="G4 reject draft",
            summary="Time-lapse embryo imaging improves IVF selection.",
        )

        with pytest.raises(PromotionRejected) as exc_info:
            store.promote_kb_draft(draft_id=draft.entry_id)

        assert RejectionReason.G4_FACTUAL_FAILED in exc_info.value.reasons
        assert _marker_path(store, draft.entry_id).is_file()
        g4_meta = store.index.get_entry(draft.entry_id)
        assert g4_meta is not None and g4_meta["tier"] == "02-Draft"

    def test_promote_admission_fails_closed_without_source_ids(
        self, store: KBStore
    ) -> None:
        """A legacy draft with no source_ids cannot be promoted (fail closed)."""
        raw = make_scored_raw(store)
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="No-source-ids draft",
        )
        # Simulate a pre-provenance draft: strip source_ids from custom_fields
        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None
        cf = json.loads(meta["custom_fields"] or "{}")
        cf["source_ids"] = []
        with store.index._connect() as conn:
            conn.execute(
                "UPDATE entries SET custom_fields = ? WHERE entry_id = ?",
                (json.dumps(cf), draft.entry_id),
            )

        with pytest.raises(PromotionRejected) as exc_info:
            store.promote_kb_draft(draft_id=draft.entry_id)

        assert RejectionReason.PROVENANCE_MISSING in exc_info.value.reasons
        assert _marker_path(store, draft.entry_id).is_file()
        closed_meta = store.index.get_entry(draft.entry_id)
        assert closed_meta is not None and closed_meta["tier"] == "02-Draft"


class TestPromoteMeta:
    """T2 acceptance path: admission passes, promotion records agent provenance."""

    def test_promote_meta_sets_agent_provenance(
        self, store: KBStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fully-eligible draft → 03-Wiki with promotion_source: agent,
        promoted_by: agent, and NO human_promoted frontmatter."""
        patch_g4(monkeypatch, passed=True)
        raw = make_scored_raw(store)
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="Admission pass draft",
            summary="Time-lapse embryo imaging improves IVF selection.",
        )

        result = store.promote_kb_draft(draft_id=draft.entry_id)

        assert result["status"] == "promoted"
        new_path = Path(result["new_path"])
        assert "03-Wiki" in new_path.parts
        assert "02-Draft" not in new_path.parts

        raw_text = new_path.read_text(encoding="utf-8")
        end = raw_text.find("---", 3)
        fm = yaml.safe_load(raw_text[3:end])
        assert fm["promotion_source"] == "agent"
        assert fm["promoted_by"] == "agent"
        assert "promoted_at" in fm
        assert "human_promoted" not in fm

        meta = store.index.get_entry(draft.entry_id)
        assert meta is not None
        assert meta["tier"] == "03-Wiki"
        # No _failed marker on the happy path
        assert not _marker_path(store, draft.entry_id).exists()
        # Original draft file moved (gone from 02-Draft)
        assert not Path(result["old_path"]).exists()

    def test_promote_meta_promoted_by_caller(
        self, store: KBStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``caller`` is recorded in promoted_by; promotion_source stays agent."""
        patch_g4(monkeypatch, passed=True)
        raw = make_scored_raw(store)
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="Caller provenance draft",
        )

        result = store.promote_kb_draft(
            draft_id=draft.entry_id, caller="agent-editor"
        )

        raw_text = Path(result["new_path"]).read_text(encoding="utf-8")
        end = raw_text.find("---", 3)
        fm = yaml.safe_load(raw_text[3:end])
        assert fm["promotion_source"] == "agent"
        assert fm["promoted_by"] == "agent-editor"

    def test_promote_keeps_working_for_already_wiki_entry(
        self, store: KBStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Idempotency: promoting a non-Draft entry still errors as before."""
        patch_g4(monkeypatch, passed=True)
        raw = make_scored_raw(store)
        draft = store.create_kb_draft(
            raw_ids=[raw.entry_id],
            title="Idempotency draft",
        )
        store.promote_kb_draft(draft_id=draft.entry_id)

        with pytest.raises(ValueError, match="not a Draft"):
            store.promote_kb_draft(draft_id=draft.entry_id)
