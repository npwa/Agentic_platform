"""Regression eval suite for the agent graph.

Deliberately deterministic: no Ollama, Chroma, or Langfuse server required,
so this runs in CI (see .github/workflows/eval.yml) without any local model
or self-hosted service. Per README.md step 5, even a naive "did the
validator pass" check counts as a regression gate -- that's what most of
these are.
"""

import os
from pathlib import Path

import pytest

from agent.graph import (
    MAX_RETRIES,
    rejected,
    rollback,
    route_after_approval,
    route_after_validation,
    validator,
    write_report,
)
from agent.graph_db import run_query
from agent.tools import get_peak_power_unit, get_unit_material

# get_unit_material() and the graph-chain test below query Neo4j live -- skip
# them (rather than erroring out CI) when no NEO4J_URI is configured.
requires_neo4j = pytest.mark.skipif(
    not os.environ.get("NEO4J_URI"), reason="NEO4J_URI not set; skipping tests that need a live Neo4j instance"
)


def test_peak_power_unit_is_dcache():
    peak = get_peak_power_unit()
    assert peak["unit"] == "Dcache"
    assert peak["peak_power"] == 14.3
    assert peak["n_samples"] == 100


@requires_neo4j
def test_unit_material_lookup():
    assert get_unit_material("Dcache") == "silicon"
    assert get_unit_material("not_a_real_unit") is None


@requires_neo4j
def test_knowledge_graph_has_part_material_run_chain():
    made_of = run_query("MATCH (:Part {id: 'ev6::Dcache'})-[:MADE_OF]->(m:Material) RETURN m.id AS material")
    assert made_of and made_of[0]["material"] == "silicon"

    used_in = run_query("MATCH (:Material {id: 'silicon'})-[:USED_IN]->(r:SimulationRun) RETURN r.id AS run_id")
    assert used_in


# A short passage standing in for real retrieved datasheet text -- long
# enough to exercise the quote-grounding check without needing a real PDF.
_SAMPLE_CONTEXT_TEXT = (
    "The device must be handled according to moisture sensitivity level "
    "requirements before the reflow soldering process begins."
)
_VERBATIM_QUOTE = "moisture sensitivity level requirements before the reflow soldering"


def _state(draft, unit="Dcache", material="silicon", sources=("J-STD-033D.PDF",), retries=0, context_text=_SAMPLE_CONTEXT_TEXT):
    return {
        "draft": draft,
        "facts": {"unit": unit, "material": material, "peak_power": 14.3, "avg_power": 10.3},
        "context": [{"source": s, "page": 1, "text": context_text} for s in sources],
        "retries": retries,
    }


def test_validator_passes_a_grounded_draft():
    state = _state(f'The Dcache unit, made of silicon, states "{_VERBATIM_QUOTE}" per (J-STD-033D.PDF).')
    result = validator(state)
    assert result["validation"] == {"passed": True, "issues": []}
    assert result["retries"] == 0


def test_validator_flags_missing_unit_name():
    state = _state(f'This silicon component states "{_VERBATIM_QUOTE}" (J-STD-033D.PDF) but never names itself.')
    result = validator(state)
    assert result["validation"]["passed"] is False
    assert any("unit name" in issue for issue in result["validation"]["issues"])
    assert result["retries"] == 1


def test_validator_flags_missing_material():
    state = _state(f'The Dcache unit states "{_VERBATIM_QUOTE}" per (J-STD-033D.PDF).')
    result = validator(state)
    assert result["validation"]["passed"] is False
    assert any("material" in issue for issue in result["validation"]["issues"])


def test_validator_flags_missing_citation():
    state = _state(f'The Dcache unit is made of silicon and states "{_VERBATIM_QUOTE}".')
    result = validator(state)
    assert result["validation"]["passed"] is False
    assert any("cite" in issue for issue in result["validation"]["issues"])


def test_validator_flags_missing_quote():
    """Unit, material, and citation are all present, but no claim is
    grounded with a verbatim quote from the retrieved context."""
    state = _state("The Dcache unit, made of silicon, has thermal risks per (J-STD-033D.PDF).")
    result = validator(state)
    assert result["validation"]["passed"] is False
    assert any("no verbatim quote" in issue for issue in result["validation"]["issues"])
    assert result["retries"] == 1


def test_validator_flags_unverifiable_quote():
    """A quote is present and looks like a citation, but the quoted text
    was never actually retrieved -- the case that motivated this check:
    correct filename/page, fabricated or paraphrased content."""
    state = _state(
        'The Dcache unit, made of silicon, states "this exact phrase was never '
        'in any retrieved excerpt" per (J-STD-033D.PDF).'
    )
    result = validator(state)
    assert result["validation"]["passed"] is False
    assert any("does not appear verbatim" in issue for issue in result["validation"]["issues"])


def test_validator_quote_match_ignores_whitespace_differences():
    """A quote that's verbatim but re-wrapped across lines (as PDF-extracted
    text often is) should still pass -- whitespace shouldn't cause a false
    rejection of a genuinely accurate quote."""
    wrapped_context = "moisture sensitivity level\nrequirements   before the\nreflow soldering"
    state = _state(
        f'The Dcache unit, made of silicon, states "{_VERBATIM_QUOTE}" per (J-STD-033D.PDF).',
        context_text=wrapped_context,
    )
    result = validator(state)
    assert result["validation"] == {"passed": True, "issues": []}


def test_route_after_validation_branches():
    assert route_after_validation({"validation": {"passed": True, "issues": []}, "retries": 0}) == "approved"
    assert route_after_validation({"validation": {"passed": False, "issues": ["x"]}, "retries": 1}) == "retry"
    assert (
        route_after_validation({"validation": {"passed": False, "issues": ["x"]}, "retries": MAX_RETRIES + 1})
        == "rollback"
    )


def test_rollback_sets_failed_status():
    result = rollback({"validation": {"passed": False, "issues": ["missing unit name"]}})
    assert result["status"] == "failed"
    assert "missing unit name" in result["draft"]


def test_route_after_approval_branches():
    assert route_after_approval({"approved": True}) == "write_report"
    assert route_after_approval({"approved": False}) == "rejected"


def test_rejected_writes_nothing():
    result = rejected({})
    assert result == {"status": "rejected", "report_path": None}


def test_write_report_creates_file(tmp_path, monkeypatch):
    import agent.graph as graph_module

    monkeypatch.setattr(graph_module, "REPORTS_DIR", tmp_path)
    result = write_report({"facts": {"unit": "Dcache"}, "draft": "test draft content"})

    assert result["status"] == "written"
    report_path = Path(result["report_path"])
    assert report_path.exists()
    assert "test draft content" in report_path.read_text()
