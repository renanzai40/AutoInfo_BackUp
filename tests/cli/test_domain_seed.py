"""Tests for concierge-wave task 15: ``autoinfo domain init <name> --seed``.

Covers:
    - Flagship demo-domain sources.yaml carry a non-empty ``extract_fields``
      (medical-research + financial-intelligence)
    - ``domain init --seed`` happy path: seeds the full demo domain into an
      existing project config (sources / topics / extract_fields)
    - ``domain init --seed`` over an ``autoinfo init --demo``-seeded domain:
      injects extract_fields, does NOT duplicate sources/topics
    - Idempotency: re-running does not duplicate sources
    - Reproducibility: two independent temp projects seed byte-identical
      domain config blocks
    - Error path: unknown domain exits non-zero; no config -> non-zero
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MEDICAL_SOURCES = (
    _REPO_ROOT
    / "src"
    / "autoinfo"
    / "data"
    / "domains"
    / "medical-research"
    / "sources.yaml"
)
_FINANCIAL_SOURCES = (
    _REPO_ROOT
    / "src"
    / "autoinfo"
    / "data"
    / "domains"
    / "financial-intelligence"
    / "sources.yaml"
)

# Plan task-15 default schemas (medical/financial flagship extract_fields).
_MEDICAL_EXTRACT_FIELDS = [
    "disease_area",
    "intervention",
    "study_type",
    "outcome_measure",
    "sample_size",
    "journal",
    "publication_date",
]
_FINANCIAL_EXTRACT_FIELDS = [
    "company",
    "sector",
    "event_type",
    "financial_metric",
    "currency",
    "region",
    "date",
]


def _write_min_config(root: Path) -> Path:
    """Create a minimal initialized project config under *root*."""
    config_dir = root / ".autoinfo"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.yaml"
    with open(config_path, "w", encoding="utf-8") as fh:
        yaml.dump(
            {
                "project": {"name": "Test Project", "created_at": "2026-07-01"},
                "llm": {
                    "provider": "openrouter",
                    "model": "deepseek/deepseek-chat",
                    "api_key": "${AUTOINFO_LLM_API_KEY}",
                },
                "domains": [],
            },
            fh,
            default_flow_style=False,
        )
    return config_path


def _read_config(root: Path) -> dict:
    with open(root / ".autoinfo" / "config.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _invoke_cli(root: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]):
    monkeypatch.chdir(root)
    from typer.testing import CliRunner

    from autoinfo.cli import app

    return CliRunner().invoke(app, args)


# ==========================================================================
# Demo-domain sources.yaml extract_fields (acceptance #1)
# ==========================================================================


class TestFlagshipExtractFields:
    """Both flagship sources.yaml files carry non-empty extract_fields."""

    @pytest.mark.parametrize(
        "yaml_path,expected",
        [
            pytest.param(_MEDICAL_SOURCES, _MEDICAL_EXTRACT_FIELDS, id="medical-research"),
            pytest.param(
                _FINANCIAL_SOURCES, _FINANCIAL_EXTRACT_FIELDS, id="financial-intelligence"
            ),
        ],
    )
    def test_extract_fields_present_and_non_empty(
        self, yaml_path: Path, expected: list[str]
    ) -> None:
        with open(yaml_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        fields = data.get("extract_fields")
        assert isinstance(fields, list) and fields, f"{yaml_path} missing extract_fields"
        assert fields == expected

    def test_medical_sources_and_topics_unchanged(self) -> None:
        """Guard: extract_fields is additive — 7 sources / 6 topics intact."""
        with open(_MEDICAL_SOURCES, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        assert len(data["sources"]) == 7
        assert len(data["topics"]) == 6

    def test_financial_sources_and_topics_unchanged(self) -> None:
        """Guard: extract_fields is additive — 11 sources / 5 topics intact."""
        with open(_FINANCIAL_SOURCES, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        assert len(data["sources"]) == 11
        assert len(data["topics"]) == 5


# ==========================================================================
# domain init --seed — happy path
# ==========================================================================


class TestDomainInitSeed:
    """``autoinfo domain init <name> --seed`` seeds the flagship domain."""

    def test_seed_medical_research(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_min_config(tmp_path)
        result = _invoke_cli(
            tmp_path, monkeypatch, ["domain", "init", "medical-research", "--seed"]
        )
        assert result.exit_code == 0, result.stdout

        cfg = _read_config(tmp_path)
        domain = next(
            d for d in cfg["domains"] if d["name"] == "medical-research"
        )
        assert len(domain["sources"]) == 7
        assert len(domain["topics"]) == 6
        assert domain["extract_fields"] == _MEDICAL_EXTRACT_FIELDS
        assert domain["active"] is True
        # description carried from the demo YAML
        assert domain.get("description")

    def test_seed_financial_intelligence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_min_config(tmp_path)
        result = _invoke_cli(
            tmp_path, monkeypatch, ["domain", "init", "financial-intelligence", "--seed"]
        )
        assert result.exit_code == 0, result.stdout

        cfg = _read_config(tmp_path)
        domain = next(
            d for d in cfg["domains"] if d["name"] == "financial-intelligence"
        )
        assert len(domain["sources"]) == 11
        assert len(domain["topics"]) == 5
        assert domain["extract_fields"] == _FINANCIAL_EXTRACT_FIELDS
        # BYOK env-refs survive the seed (raw-YAML path, not dataclass env
        # resolution) — the Finnhub settings keep ${FINNHUB_API_KEY} refs.
        finnhub = next(s for s in domain["sources"] if s["name"] == "Finnhub")
        finnhub_str = yaml.safe_dump(finnhub)
        assert "${FINNHUB_API_KEY}" in finnhub_str

    def test_seed_injects_extract_fields_into_init_demo_domain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Seeding over an ``autoinfo init --demo``-created domain injects
        extract_fields without duplicating sources/topics."""
        _write_min_config(tmp_path)
        # Simulate `autoinfo init --demo medical-research`: raw dict block,
        # sources/topics but NO extract_fields (init.py seeds raw dicts).
        with open(_MEDICAL_SOURCES, "r", encoding="utf-8") as fh:
            demo = yaml.safe_load(fh)
        cfg_path = tmp_path / ".autoinfo" / "config.yaml"
        with open(cfg_path, "r", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh)
        cfg["domains"].append(
            {
                "name": "medical-research",
                "active": True,
                "sources": demo["sources"],
                "topics": demo["topics"],
            }
        )
        with open(cfg_path, "w", encoding="utf-8") as fh:
            yaml.dump(cfg, fh, default_flow_style=False, sort_keys=False)

        result = _invoke_cli(
            tmp_path, monkeypatch, ["domain", "init", "medical-research", "--seed"]
        )
        assert result.exit_code == 0, result.stdout

        cfg_after = _read_config(tmp_path)
        assert len(cfg_after["domains"]) == 1, "seed must not duplicate the domain"
        domain = cfg_after["domains"][0]
        assert len(domain["sources"]) == 7, "sources must not be duplicated"
        assert len(domain["topics"]) == 6, "topics must not be duplicated"
        assert domain["extract_fields"] == _MEDICAL_EXTRACT_FIELDS
        # additive backfill only — pre-existing domain content untouched
        assert domain["active"] is True

    # ------------------------------------------------------------------
    # Idempotency (acceptance #3)
    # ------------------------------------------------------------------

    def test_seed_idempotent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_min_config(tmp_path)
        first = _invoke_cli(
            tmp_path, monkeypatch, ["domain", "init", "medical-research", "--seed"]
        )
        assert first.exit_code == 0
        cfg_first = _read_config(tmp_path)

        second = _invoke_cli(
            tmp_path, monkeypatch, ["domain", "init", "medical-research", "--seed"]
        )
        assert second.exit_code == 0
        assert "already" in second.stdout.lower()

        cfg_second = _read_config(tmp_path)
        assert cfg_second == cfg_first, "re-seed must not change the config"
        assert len(cfg_second["domains"]) == 1

    # ------------------------------------------------------------------
    # Reproducibility (acceptance #5): two independent temp dirs produce
    # byte-identical domain config blocks.
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("domain_name", ["medical-research", "financial-intelligence"])
    def test_seed_reproducible_across_temp_dirs(
        self,
        tmp_path_factory: pytest.TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
        domain_name: str,
    ) -> None:
        dir_a = tmp_path_factory.mktemp("seed-a")
        dir_b = tmp_path_factory.mktemp("seed-b")
        for root in (dir_a, dir_b):
            _write_min_config(root)
            result = _invoke_cli(root, monkeypatch, ["domain", "init", domain_name, "--seed"])
            assert result.exit_code == 0

        def _domain_block(root: Path) -> str:
            cfg = _read_config(root)
            domain = next(d for d in cfg["domains"] if d["name"] == domain_name)
            return yaml.safe_dump(domain, sort_keys=False, allow_unicode=True)

        assert _domain_block(dir_a) == _domain_block(dir_b)

    # ------------------------------------------------------------------
    # Error paths
    # ------------------------------------------------------------------

    def test_seed_unknown_domain_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_min_config(tmp_path)
        result = _invoke_cli(
            tmp_path, monkeypatch, ["domain", "init", "nonexistent-domain", "--seed"]
        )
        assert result.exit_code != 0

    def test_seed_without_config_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _invoke_cli(
            tmp_path, monkeypatch, ["domain", "init", "medical-research", "--seed"]
        )
        assert result.exit_code != 0

    def test_domain_show_displays_extract_fields(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`domain show` surfaces the seeded extract_fields (acceptance #2)."""
        _write_min_config(tmp_path)
        seeded = _invoke_cli(
            tmp_path, monkeypatch, ["domain", "init", "medical-research", "--seed"]
        )
        assert seeded.exit_code == 0

        shown = _invoke_cli(
            tmp_path, monkeypatch, ["domain", "show", "--name", "medical-research"]
        )
        assert shown.exit_code == 0
        output = shown.stdout + shown.stderr
        assert "Sources:       7" in output
        assert "Topics:        6" in output
        assert "Extract fields:" in output
        assert "disease_area" in output
