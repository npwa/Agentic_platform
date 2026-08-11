"""Regression eval suite for the agent graph.

Deliberately deterministic: no Ollama, Chroma, or Langfuse server required,
so this runs in CI (see .github/workflows/eval.yml) without any local model
or self-hosted service. Per README.md step 5, even a naive "did the
validator pass" check counts as a regression gate -- that's what most of
these are.
"""

from pathlib import Path

import networkx as nx

from agent.graph import (
    MAX_RETRIES,
    rejected,
    rollback,
    route_after_approval,
    route_after_validation,
    validator,
    write_report,
)
from agent.tools import GRAPH_PATH, get_peak_power_unit, get_unit_material


def test_peak_power_unit_is_dcache():
    peak = get_peak_power_unit()
    assert peak["unit"] == "Dcache"
    assert peak["peak_power"] == 14.3
    assert peak["n_samples"] == 100


def test_unit_material_lookup():
    assert get_unit_material("Dcache") == "silicon"
    assert get_unit_material("not_a_real_unit") is None


def test_knowledge_graph_has_part_material_run_chain():
    graph = nx.read_graphml(GRAPH_PATH)
    assert graph.nodes["ev6::Dcache"]["kind"] == "part"
    assert any(
        target == "silicon" and data["relation"] == "made_of"
        for _, target, data in graph.out_edges("ev6::Dcache", data=True)
    )
    assert any(data["relation"] == "used_in" for _, _, data in graph.out_edges("silicon", data=True))


def _state(draft, unit="Dcache", material="silicon", sources=("J-STD-033D.PDF",), retries=0):
    return {
        "draft": draft,
        "facts": {"unit": unit, "material": material, "peak_power": 14.3, "avg_power": 10.3},
        "context": [{"source": s, "page": 1, "text": "..."} for s in sources],
        "retries": retries,
    }


def test_validator_passes_a_grounded_draft():
    state = _state("The Dcache unit, made of silicon, per (J-STD-033D.PDF).")
    result = validator(state)
    assert result["validation"] == {"passed": True, "issues": []}
    assert result["retries"] == 0


def test_validator_flags_missing_unit_name():
    state = _state("This silicon component cites (J-STD-033D.PDF) but never names itself.")
    result = validator(state)
    assert result["validation"]["passed"] is False
    assert any("unit name" in issue for issue in result["validation"]["issues"])
    assert result["retries"] == 1


def test_validator_flags_missing_material():
    state = _state("The Dcache unit draws power, per (J-STD-033D.PDF).")
    result = validator(state)
    assert result["validation"]["passed"] is False
    assert any("material" in issue for issue in result["validation"]["issues"])


def test_validator_flags_missing_citation():
    state = _state("The Dcache unit is made of silicon.")
    result = validator(state)
    assert result["validation"]["passed"] is False
    assert any("cite" in issue for issue in result["validation"]["issues"])


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
