"""Integration tests – Unit 12.

Exercises the full pipeline end-to-end using synthetic data that crosses
the 50→51 pricing tier boundary so variants with positive savings are produced.
"""
from __future__ import annotations

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from analyzer.config_loader import get_pricing, get_ranking_weights, load_config
from analyzer.constraints import classify
from analyzer.impact_prognozer import prognosticate_impact
from analyzer.json_output import save_analysis, load_analysis
from analyzer.memory import clear_decisions, load_decisions, record_decision
from analyzer.models import Document, Variant
from analyzer.optimizer import generate_variants
from analyzer.pdf_generator import generate_report
from analyzer.ranker import load_decisions_from_engine, rank_variants
from analyzer.rules import RuleEngine
from analyzer.tax_advisor import assess_all
from tests.conftest import make_doc, make_variant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _engine(tmp_path: Path, klient_id: str = "INTEG") -> RuleEngine:
    return RuleEngine(klient_id=klient_id, data_dir=tmp_path)


# ---------------------------------------------------------------------------
# Pipeline: parse → assess → classify → generate → rank
# ---------------------------------------------------------------------------

class TestFullPipeline:
    def test_pipeline_produces_variants(self, docs_crossing_tier, tmp_path):
        """52 LOW-risk docs + KPIR → at least one variant with savings > 0."""
        docs = assess_all(docs_crossing_tier, "KPIR")
        engine = _engine(tmp_path)
        result = classify(docs, "KPIR", engine)

        variants_raw = generate_variants(result.remaining, no_go_count=len(result.no_go))
        top = rank_variants(variants_raw, decisions=[], top_n=5)

        assert len(top) > 0
        assert all(v.oszczędność > 0 for v in top)

    def test_pipeline_sorted_by_score(self, docs_crossing_tier, tmp_path):
        docs = assess_all(docs_crossing_tier, "KPIR")
        engine = _engine(tmp_path)
        result = classify(docs, "KPIR", engine)
        raw = generate_variants(result.remaining, no_go_count=len(result.no_go))
        top = rank_variants(raw, decisions=[], top_n=5)

        scores = [v.score for v in top]
        assert scores == sorted(scores, reverse=True)

    def test_pipeline_top_n_respected(self, docs_crossing_tier, tmp_path):
        docs = assess_all(docs_crossing_tier, "KPIR")
        engine = _engine(tmp_path)
        result = classify(docs, "KPIR", engine)
        raw = generate_variants(result.remaining, no_go_count=len(result.no_go))

        for top_n in (1, 3, 5):
            top = rank_variants(raw, decisions=[], top_n=top_n)
            assert len(top) <= top_n

    def test_pipeline_no_go_contains_high_risk(self, tmp_path):
        """HIGH-risk doc must end up in no_go, not remaining."""
        low_docs = [make_doc(f"l{i}", risk="LOW") for i in range(3)]
        high_doc = make_doc("high_1", risk="HIGH")
        docs = low_docs + [high_doc]

        engine = _engine(tmp_path)
        result = classify(docs, "KPIR", engine)

        no_go_ids = {d.id for d in result.no_go}
        assert "high_1" in no_go_ids
        assert all(d.id != "high_1" for d in result.remaining)

    def test_pipeline_with_sample_xml(self, sample_xml_bytes, tmp_path):
        """Sample fixture has only 5 docs – no variants expected, but no crash."""
        from analyzer.parser import parse_jpk_fa
        docs = parse_jpk_fa(sample_xml_bytes)
        docs = assess_all(docs, "KPIR")
        engine = _engine(tmp_path)
        result = classify(docs, "KPIR", engine)
        raw = generate_variants(result.remaining, no_go_count=len(result.no_go))
        top = rank_variants(raw, decisions=[], top_n=5)
        assert isinstance(top, list)

    def test_pipeline_with_config(self, docs_crossing_tier, tmp_path):
        """Pipeline using pricing and weights loaded from config.json."""
        pricing = get_pricing()
        weights = get_ranking_weights()
        docs = assess_all(docs_crossing_tier, "KPIR")
        engine = _engine(tmp_path)
        result = classify(docs, "KPIR", engine)
        raw = generate_variants(result.remaining, no_go_count=len(result.no_go), pricing=pricing)
        top = rank_variants(raw, decisions=[], top_n=5, weights=weights)
        assert isinstance(top, list)


# ---------------------------------------------------------------------------
# Memory: decision recording changes compatibility score
# ---------------------------------------------------------------------------

class TestMemoryIntegration:
    def test_record_then_load(self, ranked_variants, tmp_path):
        engine = _engine(tmp_path)
        v = ranked_variants[0]
        record_decision(engine, v)
        decisions = load_decisions(engine)
        assert len(decisions) == 1

    def test_multiple_records_accumulate(self, ranked_variants, tmp_path):
        engine = _engine(tmp_path)
        for v in ranked_variants:
            record_decision(engine, v)
        decisions = load_decisions(engine)
        assert len(decisions) == len(ranked_variants)

    def test_compatibility_improves_after_decisions(self, docs_crossing_tier, tmp_path):
        """After 5 identical decisions, compatibility score for matching variants rises."""
        engine = _engine(tmp_path)
        docs = assess_all(docs_crossing_tier, "KPIR")
        result = classify(docs, "KPIR", engine)
        raw = generate_variants(result.remaining, no_go_count=len(result.no_go))
        top_before = rank_variants(raw[:], decisions=[], top_n=3)
        compat_before = top_before[0].compatibility_score if top_before else 0.5

        # Record 5 decisions all matching top variant's features
        best = top_before[0] if top_before else make_variant()
        for _ in range(5):
            record_decision(engine, best)

        decisions = load_decisions_from_engine(engine)
        top_after = rank_variants(raw[:], decisions=decisions, top_n=3)
        compat_after = top_after[0].compatibility_score if top_after else 0.5

        assert compat_after >= compat_before

    def test_clear_decisions(self, ranked_variants, tmp_path):
        engine = _engine(tmp_path)
        for v in ranked_variants:
            record_decision(engine, v)
        clear_decisions(engine)
        assert load_decisions(engine) == []

    def test_rules_survive_decision_record(self, tmp_path):
        """Recording decisions must not overwrite existing client rules."""
        from analyzer.rules import ActionRule
        engine = _engine(tmp_path)
        rule = ActionRule(
            id="integ_rule", nazwa="Integ", działanie="sugeruj_pomijanie",
            typ="client_preference",
        )
        engine.add_client_rule(rule)

        record_decision(engine, make_variant())

        data = json.loads(engine.client_rules_path.read_text(encoding="utf-8"))
        assert any(r["id"] == "integ_rule" for r in data["rules"])
        assert len(data["decisions"]) == 1


# ---------------------------------------------------------------------------
# Impact prognosis integration
# ---------------------------------------------------------------------------

class TestImpactIntegration:
    def test_impact_set_on_shift_variants(self, docs_crossing_tier, tmp_path):
        """Variants with przesunięcia get an impact_message after prognostication."""
        engine = _engine(tmp_path)
        raw = generate_variants(
            docs_crossing_tier,
            no_go_count=0,
            target_period="2024-12",
        )
        top = rank_variants(raw, decisions=[], top_n=5)

        for v in top:
            prognosticate_impact(v, docs_per_month={"2024-12": 0})

        shift_variants = [v for v in top if v.dokumenty_do_przesunięcia]
        for v in shift_variants:
            assert v.impact_message is not None

    def test_no_shift_no_impact_message(self, ranked_variants):
        """Variants with no shifts get impact_message=None."""
        for v in ranked_variants:
            if not v.dokumenty_do_przesunięcia:
                prognosticate_impact(v)
                assert v.impact_message is None


# ---------------------------------------------------------------------------
# PDF generation integration
# ---------------------------------------------------------------------------

class TestPdfIntegration:
    def test_pdf_generated_from_pipeline(self, ranked_variants, tmp_path):
        out = tmp_path / "report.pdf"
        generate_report(ranked_variants, klient_id="INTEG", output_path=out, period="2024-11")
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"

    def test_pdf_non_trivial_size(self, ranked_variants, tmp_path):
        out = tmp_path / "r.pdf"
        generate_report(ranked_variants, klient_id="INTEG", output_path=out)
        assert out.stat().st_size > 3000

    def test_pdf_empty_variants(self, tmp_path):
        out = tmp_path / "empty.pdf"
        generate_report([], klient_id="INTEG", output_path=out)
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# JSON output integration
# ---------------------------------------------------------------------------

class TestJsonIntegration:
    def test_json_roundtrip(self, ranked_variants, tmp_path):
        out = tmp_path / "analysis.json"
        save_analysis(ranked_variants, klient_id="INTEG", output_path=out, period="2024-11")
        loaded = load_analysis(out)
        assert loaded["klient_id"] == "INTEG"
        assert loaded["period"] == "2024-11"
        assert len(loaded["variants"]) == len(ranked_variants)

    def test_json_savings_preserved(self, ranked_variants, tmp_path):
        out = tmp_path / "a.json"
        save_analysis(ranked_variants, klient_id="INTEG", output_path=out)
        loaded = load_analysis(out)
        for orig, saved in zip(ranked_variants, loaded["variants"]):
            assert saved["oszczędność"] == str(orig.oszczędność)

    def test_json_valid_utf8_polish(self, tmp_path):
        """Polish characters must survive JSON roundtrip."""
        v = make_variant(pomijanie=[make_doc("p1")])
        v.impact_message = "Grudzień będzie miał 53 dokumentów (+5)"
        out = tmp_path / "utf.json"
        save_analysis([v], klient_id="Klient_Ząbkowski", output_path=out)
        raw = out.read_text(encoding="utf-8")
        assert "Klient_Ząbkowski" in raw
        assert "Grudzień" in raw


# ---------------------------------------------------------------------------
# Config × pipeline integration
# ---------------------------------------------------------------------------

class TestConfigPipelineIntegration:
    def test_pricing_from_config_matches_optimizer_default(self):
        from analyzer.optimizer import Pricing
        config_pricing = get_pricing()
        default = Pricing.default()
        for count in (0, 50, 51, 100, 101, 200, 201, 500):
            assert config_pricing.price_for(count) == default.price_for(count)

    def test_weights_from_config_sum_to_one(self):
        weights = get_ranking_weights()
        assert abs(sum(weights.values()) - 1.0) < 1e-9

    def test_full_pipeline_config_driven(self, docs_crossing_tier, tmp_path):
        """Full pipeline using all values sourced from config.json."""
        cfg = load_config()
        pricing = get_pricing(cfg)
        weights = get_ranking_weights(cfg)
        top_n = cfg["app"]["default_top_n"]

        docs = assess_all(docs_crossing_tier, "KPIR")
        engine = _engine(tmp_path)
        result = classify(docs, "KPIR", engine)
        raw = generate_variants(
            result.remaining,
            no_go_count=len(result.no_go),
            pricing=pricing,
        )
        top = rank_variants(raw, decisions=[], top_n=top_n, weights=weights)

        assert len(top) <= top_n
        assert all(isinstance(v, Variant) for v in top)
