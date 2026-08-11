"""The agent graph: planner -> executor -> validator, with a retry edge back
to the executor on a failed validation and a rollback edge once retries are
exhausted. Once a draft is validated, a human_approval interrupt node pauses
the graph before the one "write" action (saving a report to disk) — the
autonomy boundary called for in the README's step 4.

State is explicit (a TypedDict) and every field is inspectable after a run,
which is the point of building this on LangGraph instead of a bare LLM
call: the control flow (who ran, in what order, with what facts) is the
artifact, not just the final text.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from agent.config import MAX_RETRIES, MODEL, OLLAMA_BASE_URL, PROMPTS
from agent.tools import get_peak_power_unit, get_unit_material, retrieve_context
from agent.tracing import langfuse_handler

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


class AgentState(TypedDict):
    task: str
    plan: str
    facts: dict
    context: list[dict]
    draft: str
    validation: dict
    retries: int
    status: str
    approved: bool | None
    report_path: str | None


def _llm(temperature: float = 0.2) -> ChatOpenAI:
    return ChatOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama", model=MODEL, temperature=temperature)


def planner(state: AgentState) -> dict:
    prompt = PROMPTS["planner"].format(task=state["task"])
    response = _llm(temperature=0.0).invoke(prompt, config={"callbacks": [langfuse_handler]})
    return {"plan": response.content}


def executor(state: AgentState) -> dict:
    facts = state.get("facts") or {}
    if not facts:
        peak = get_peak_power_unit()
        material = get_unit_material(peak["unit"])
        facts = {**peak, "material": material}

    context = state.get("context") or retrieve_context(
        f"{facts['material']} thermal resistance package moisture sensitivity junction temperature"
    )

    feedback = ""
    if state.get("validation") and not state["validation"].get("passed", True):
        feedback = (
            "\n\nYour previous draft failed validation for these reasons: "
            + "; ".join(state["validation"]["issues"])
            + ". Fix them in this revision."
        )

    context_block = "\n".join(f"- ({c['source']} p.{c['page']}) {c['text'][:300]}" for c in context)
    prompt = PROMPTS["executor"].format(
        plan=state["plan"],
        unit=facts["unit"],
        material=facts["material"],
        peak_power=f"{facts['peak_power']:.2f}",
        avg_power=f"{facts['avg_power']:.2f}",
        context_block=context_block,
        feedback=feedback,
    )
    response = _llm(temperature=0.2).invoke(prompt, config={"callbacks": [langfuse_handler]})
    return {"facts": facts, "context": context, "draft": response.content}


def validator(state: AgentState) -> dict:
    draft = state["draft"].lower()
    facts = state["facts"]
    issues = []

    if facts["unit"].lower() not in draft:
        issues.append(f"draft does not mention the unit name '{facts['unit']}'")
    if facts["material"].lower() not in draft:
        issues.append(f"draft does not mention the material '{facts['material']}'")
    if not any(c["source"].lower() in draft for c in state["context"]):
        issues.append("draft does not cite any of the retrieved datasheet sources by filename")

    passed = not issues
    retries = state.get("retries", 0)
    return {
        "validation": {"passed": passed, "issues": issues},
        "retries": retries if passed else retries + 1,
    }


def route_after_validation(state: AgentState) -> Literal["retry", "rollback", "approved"]:
    if state["validation"]["passed"]:
        return "approved"
    if state["retries"] > MAX_RETRIES:
        return "rollback"
    return "retry"


def rollback(state: AgentState) -> dict:
    return {
        "status": "failed",
        "draft": (
            "[rolled back after exhausting retries] Unresolved validation issues: "
            + "; ".join(state["validation"]["issues"])
        ),
    }


def approve(state: AgentState) -> dict:
    return {"status": "validated"}


def human_approval(state: AgentState) -> dict:
    """Interrupt the graph and wait for a human to approve or reject the
    validated draft before the write_report node runs. Resume with
    Command(resume=True) to approve or Command(resume=False) to reject."""
    decision = interrupt(
        {
            "question": "Approve this draft for writing to disk?",
            "draft": state["draft"],
            "facts": state["facts"],
        }
    )
    return {"approved": bool(decision)}


def route_after_approval(state: AgentState) -> Literal["write_report", "rejected"]:
    return "write_report" if state["approved"] else "rejected"


def write_report(state: AgentState) -> dict:
    """The one 'write' action in the graph: persist the approved draft."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORTS_DIR / f"{state['facts']['unit']}_{timestamp}.md"
    report_path.write_text(f"# Thermal risk summary: {state['facts']['unit']}\n\n{state['draft']}\n")
    return {"status": "written", "report_path": str(report_path)}


def rejected(state: AgentState) -> dict:
    return {"status": "rejected", "report_path": None}


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("planner", planner)
    graph.add_node("executor", executor)
    graph.add_node("validator", validator)
    graph.add_node("rollback", rollback)
    graph.add_node("approve", approve)
    graph.add_node("human_approval", human_approval)
    graph.add_node("write_report", write_report)
    graph.add_node("rejected", rejected)

    graph.set_entry_point("planner")
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "validator")
    graph.add_conditional_edges(
        "validator",
        route_after_validation,
        {"retry": "executor", "rollback": "rollback", "approved": "approve"},
    )
    graph.add_edge("rollback", END)
    graph.add_edge("approve", "human_approval")
    graph.add_conditional_edges(
        "human_approval",
        route_after_approval,
        {"write_report": "write_report", "rejected": "rejected"},
    )
    graph.add_edge("write_report", END)
    graph.add_edge("rejected", END)

    return graph.compile(checkpointer=InMemorySaver())
